import datetime
import random
import string

import discord
from discord import *
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import os
import cloudscraper
import math
import sqlite3
import asyncio

load_dotenv()

TOKEN = os.getenv("TOKEN")

QUEUE_CHANNEL_ID = 1374138072844996640

scraper = cloudscraper.create_scraper()




class Player:
    def __init__(self, discord_id, tracker_url):
        self.discord_id = discord_id
        self.tracker_url = tracker_url
        self.ones_rating = None
        self.twos_rating = None
        self.threes_rating = None


    def __repr__(self):
        return f"Player(discord_id={self.discord_id}, ones={self.ones_rating}, twos={self.twos_rating}, threes={self.threes_rating})"


class Match:
    def __init__(self, match_id, gamemode, time_created,team_a_ids,team_b_ids ,player_ids, status="ongoing",
                 score_a=None, score_b=None, time_completed=None):
        self.match_id = match_id
        self.gamemode = gamemode
        self.time_created = datetime.datetime.now()
        self.player_ids = player_ids
        self.team_a_ids = team_a_ids
        self.team_b_ids = team_b_ids
        self.status = status
        self.score_a = score_a
        self.score_b = score_b
        self.time_completed = time_completed

    def submit_score_function(self, score_a, score_b):
        self.score_a = score_a
        self.score_b = score_b
        self.status = "completed"
        self.time_completed = datetime.datetime.now()

        conn = sqlite3.connect("scrim.db")
        c = conn.cursor()
        c.execute("""
            UPDATE matches
            SET status = ?, score_a = ?, score_b = ?, time_completed = ?
            WHERE match_id = ?""", (self.status, self.score_a, self.score_b, self.time_completed.isoformat(), self.match_id))
        conn.commit()
        conn.close()

class WinnerVoteView(discord.ui.View):
    def __init__(self, match_id, req_votes, player_ids, messages=None ):
        super().__init__(timeout=120)
        self.match_id = match_id
        self.req_votes = req_votes
        self.messages = messages or []
        self.player_ids = player_ids

    @discord.ui.button(label="Team A Won", style=discord.ButtonStyle.blurple)
    async def vote_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_vote(interaction, 1)
    #this the 1st button

    @discord.ui.button(label="Team B Won", style=discord.ButtonStyle.red)
    async def vote_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_vote(interaction, 2)
    #this the 2nd button

    async def record_vote(self, interaction: discord.Interaction, choice: int):
        user_id = interaction.user.id
        votes = queue_votes.setdefault(self.match_id, {})

        if votes.get(user_id) == choice:
            del votes[user_id]
        else:
            votes[user_id] = choice

        await interaction.response.defer()
        await self.broadcast_update()
    #this puts the choice in a list inside a dict, then updates all messages with the new current votes

    def get_counts(self):
        votes = queue_votes.get(self.match_id, {})
        team_a = sum(1 for v in votes.values() if v == 1)
        team_b = sum(1 for v in votes.values() if v == 2)
        return team_a, team_b
    #this sees the votes and checks to see if its at the needed amount to complete and assign winner, is called a lot

    def get_winner(self):
        team_a, team_b = self.get_counts()
        if team_a > team_b:
            return 1
        elif team_b > team_a:
            return 2
        return None
    #this just returns which team won

    def build_embed(self, status=None):
        team_a, team_b = self.get_counts()
        embed = discord.Embed(title=f"Match #{self.match_id} — Who Won?", color=discord.Color.blurple())
        embed.add_field(name="Team A players")
        embed.add_field(name="Team A", value=str(team_a), inline=True)
        embed.add_field(name="Team B", value=str(team_b), inline=True)

        if status == "resolved":
            winner = self.get_winner()
            embed.description = f"**{'Team A' if winner == 1 else 'Team B'} wins!**"
            embed.set_footer(text="Vote confirmed")
        elif status == "timeout_decided":
            winner = self.get_winner()
            embed.description = f"**{'Team A' if winner == 1 else 'Team B'} wins** (majority vote, time expired)"
            embed.set_footer(text="Vote closed")
        elif status == "timeout_tied":
            embed.description = "**Winner not decided — match doesn't count.**"
            embed.set_footer(text="Vote tied at timeout")
        else:
            embed.set_footer(text=f"{self.req_votes} votes needed to confirm")

        return embed
    #this is the embed which does most of the graphics, allows everyone to see updated votes instantly, have a title and
    #have a description and other things with details to make it look more complete

    async def broadcast_update(self):
        embed = self.build_embed()
        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        team_a, team_b = self.get_counts()
        if team_a >= self.req_votes or team_b >= self.req_votes:
            await self.resolve()
    #this changed the embed by going into every message within messages list and then changes them to what it should be
    #it is called when button is pressed so it also calls get counts and resolve if get counts has a winner

    async def resolve(self):
        for item in self.children:
            item.disabled = True

        embed = self.build_embed(status="resolved")
        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        self.stop()
        #this changed the embed to say who the winner is and set the status to resolves and make it so you cannot
        #interact with the ui anymore
        # TODO: write self.get_winner() to DB here

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        winner = self.get_winner()
        status = "timeout_tied" if winner is None else "timeout_decided"
        embed = self.build_embed(status=status)

        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue
    #this is for when the timeout is reached, if this happens it picks who has the majority votes or just defers the game

class TeamSelectView(discord.ui.View):
    def __init__(self,player_ids, match_id, gamemode, region):
        super().__init__(timeout=120)
        self.player_ids = player_ids
        self.match_id = match_id
        self.gamemode = gamemode
        self.region = region


target_names = {
    "Ranked Duel 1v1": "ones",
    "Ranked Doubles 2v2": "twos",
    "Ranked Standard 3v3": "threes",
}

queue_votes = {

}

# <editor-fold desc="Functions">

def scrape_tracker(tracker_url):
    resp = scraper.get(tracker_url)
    resp.raise_for_status()
    data = resp.json()

    segments = data["data"]["segments"]

    ranks = {}
    for seg in segments:
        name = seg.get("metadata", {}).get("name")
        seg_type = seg.get("type")
        stats = seg.get("stats", {})

        if name not in target_names:
            continue

        key = target_names[name]

        if seg_type == "playlist":
            current = stats.get("rating", {}).get("value")
            if current is not None:
                ranks[f"{key}_elo"] = current

        elif seg_type == "peak-rating":
            peak = stats.get("peakRating", {}).get("value")
            if peak is not None:
                ranks[f"{key}_peak"] = peak

    ones_mmr = ranks.get("ones_elo")
    ones_peak = ranks.get("ones_peak")
    twos_mmr = ranks.get("twos_elo")
    twos_peak = ranks.get("twos_peak")
    threes_mmr = ranks.get("threes_elo")
    threes_peak = ranks.get("threes_peak")
    print(ones_mmr, ones_peak, twos_mmr, twos_peak, threes_mmr, threes_peak)
    return get_elo(ones_mmr, ones_peak, twos_mmr, twos_peak, threes_mmr, threes_peak)

def get_elo(ones_mmr, ones_peak, twos_mmr, twos_peak, threes_mmr, threes_peak):
    ones_elo = math.ceil(ones_peak * 0.8 + ones_mmr * 0.2)
    twos_elo = math.ceil(twos_peak * 0.8 + twos_mmr * 0.2)
    threes_elo = math.ceil(threes_peak * 0.8 + threes_mmr * 0.2)
    return ones_elo, twos_elo, threes_elo

def init_db():
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            discord_id INTEGER PRIMARY KEY,
            tracker_url TEXT,
            ones_rating INTEGER,
            twos_rating INTEGER,
            threes_rating INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            gamemode TEXT NOT NULL,
            player_ids TEXT NOT NULL,
            team_a_ids TEXT NOT NULL,
            team_b_ids TEXT NOT NULL,
            status TEXT NOT NULL,
            score_a INTEGER,
            score_b INTEGER,
            time_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            time_completed TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

def save_player(player):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO players (discord_id, tracker_url, ones_rating, twos_rating, threes_rating)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            tracker_url = excluded.tracker_url,
            ones_rating = excluded.ones_rating,
            twos_rating = excluded.twos_rating,
            threes_rating = excluded.threes_rating
    """, (player.discord_id, player.tracker_url, player.ones_rating, player.twos_rating, player.threes_rating))
    conn.commit()
    conn.close()

def get_player(discord_id):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return None

    player = Player(row[0], row[1])
    player.ones_rating = row[2]
    player.twos_rating = row[3]
    player.threes_rating = row[4]
    return player

def save_match(match):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("""
            INSERT INTO matches (match_id, gamemode, player_ids, status, time_created)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                gamemode = excluded.gamemode,
                player_ids = excluded.player_ids,
                status = excluded.status,
                time_created = excluded.time_created
        """, (match.match_id, match.gamemode, match.player_ids, match.status, match.time_created))
    conn.commit()
    conn.close()

def format_link(tracker_url):
    parts = tracker_url.split("/")
    print(parts)
    platform = parts[5]
    username = parts[6]
    link = f"https://api.tracker.gg/api/v2/rocket-league/standard/profile/{platform}/{username}?"
    print(link)
    return link

async def matchmaking_loop():
    await bot.wait_until_ready()
    channel = bot.get_channel(QUEUE_CHANNEL_ID)

    while not bot.is_closed():
        for key, pool in queues.items():
            region, gamemode = key
            team_size = gamemode * 2

            if len(pool) >= team_size:
                players = pool[:team_size]
                del pool[:team_size]
                print("YESSS!!! STASRTT")
                await start_match(players, region, gamemode, channel)
        await asyncio.sleep(3)

async def start_match(players, region, gamemode, channel):
    match_id = generate_id()
    player_ids = [p.discord_id for p in players]
    view = TeamSelectView(player_ids=player_ids, match_id=match_id, gamemode=gamemode, region=region)


    # TODO: MAKE THIS GO INTO A DM, MAKE THE CLASS FOR THE TEAM VOTING AND SET IT UP WITHIN THIS FUNCTION TO WORK
    #todo: THEN CHANGE DB TO IT HAS WHICH TEAM WHICH IDS ARE IN, THEN ADD WHICH PLAYERS ON WHAT TEAM IN VOTING
    #TODO: THEN CHANGE Q TO FILTER SO ONLY ALLOWS CERTAIN MMR GAPS, THEN MAKE ELO SYSTEM

def generate_id():
    x = random.randint(1,1000)
    y = random.randint(1, 100)
    z = str(x * y)
    l = random.choices(string.ascii_letters, k=5)
    id = ""
    for char in l:
        index = random.randint(0,len(z)-1)
        s = z[:index] + char + z[index:]
        z = s
    id = z
    print(id)
    return id

def is_player_in_match(discord_id):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("SELECT player_ids FROM matches WHERE status = 'ongoing'")
    rows = cur.fetchall()
    conn.close()

    for (player_ids,) in rows:
        ids = player_ids.split(" ")
        if str(discord_id) in ids:
            return True
    return False

async def send_winner_vote_dm(match_id, player_ids, required_votes):
    view = WinnerVoteView(match_id, required_votes, player_ids = player_ids)

    for discord_id in player_ids:
        try:
            user = await bot.fetch_user(int(discord_id))
            embed = view.build_embed()
            msg = await user.send(embed=embed, view=view)
            view.messages.append(msg)
        except discord.Forbidden:
            print(f"cant dm user: {discord_id}, dms may be disabled")
        except discord.NotFound:
            print(f"Couldnt find user: {discord_id}")

# </editor-fold>

queues = {
    ("NA", 1): [],
    ("NA", 2): [],
    ("NA", 3): [],
    ("EU", 1): [],
    ("EU", 2): [],
    ("EU", 3): [],
    ("SAM", 1): [],
    ("SAM", 2): [],
    ("SAM", 3): [],
    ("MENA", 1): [],
    ("MENA", 2): [],
    ("MENA", 3): [],
    ("OCE", 1): [],
    ("OCE", 2): [],
    ("OCE", 3): [],
    ("SSA", 1): [],
    ("SSA", 2): [],
    ("SSA", 3): [],
    ("APAC", 1): [],
    ("APAC", 2): [],
    ("APAC", 3): []
}

ongoing_matches = []



# <editor-fold desc="Intents and bot setup">

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

    print(f"Logging in as {bot.user}")
    bot.loop.create_task(matchmaking_loop())


@bot.tree.command(name="ping")
async def ping(interaction):
    print("Ping command received")
    await interaction.response.send_message("Pong!")

# </editor-fold>

# <editor-fold desc="Queue Commands">

# <editor-fold desc="Join Queue">
@bot.tree.command(name="queue", description="join the scrim queue")
@app_commands.choices(
    region=[
        app_commands.Choice(name="NA", value="NA"),
        app_commands.Choice(name="EU", value="EU"),
        app_commands.Choice(name="SAM", value="SAM"),
        app_commands.Choice(name="MENA", value="MENA"),
        app_commands.Choice(name="SSA", value="SSA"),
        app_commands.Choice(name="APAC", value="APAC"),
        app_commands.Choice(name="OCE", value="OCE")
    ],
    gamemode=[
        app_commands.Choice(name="1v1", value=1),
        app_commands.Choice(name="2v2", value=2),
        app_commands.Choice(name="3v3", value=3)
    ]
)
async def queue(interaction, region: app_commands.Choice[str],
                gamemode: app_commands.Choice[int]):
    await interaction.response.defer()
    player = get_player(interaction.user.id)

    if player is None:
        await interaction.followup.send("Please use the rank check command before queueing!")
        return

    key = (region.value, gamemode.value)

    if key not in queues:
        await interaction.followup.send("Invalid region/gamemode combo!")
        return

    in_queue = is_player_in_match(discord_id=interaction.user.id)
    if in_queue == True:
        await interaction.followup.send("You are already in an ongoing match")
        return
    else:
        pass

    try: queues[key].append(player)
    except Exception as e:
        print(e)
        await interaction.followup.send("Error joining the queue!")
        return
    await interaction.followup.send(
        f"Queueing you for {gamemode.name} in {region.name} "
    )


    print(queues)
# </editor-fold>

# <editor-fold desc="Leave Queue">
@bot.tree.command()
async def leave_queue(interaction):
    await interaction.response.defer()
    player = get_player(interaction.user.id)
    print(player)
    found = None
    for key, value in queues.items():
        for p in value:
            if p.discord_id == player.discord_id:
                queues[key].remove(p)
                found = True
                break
    if found:
        await interaction.followup.send("successfully left the queue!")
    else:
        await interaction.followup.send("couldn't find you in the queue!")
    print(queues)

# </editor-fold>


# <editor-fold desc="Rank check command">
@bot.tree.command(name="rank-check", description="submit your tracker to verify your mmr")
async def rank_check(interaction, tracker_url: str):
    await interaction.response.defer()
    try:
        tracker_url = format_link(tracker_url)
    except Exception as e:
        print(e)
        await interaction.followup.send(
            "Couldnt verify the tracker!"
        )

    try:
        ones_elo, twos_elo, threes_elo = scrape_tracker(tracker_url)
    except Exception as e:
        print(e)
        await interaction.followup.send(
            "Couldnt verify the tracker!"
        )
        return

    player = Player(interaction.user.id, tracker_url)
    player.ones_rating = ones_elo
    player.twos_rating = twos_elo
    player.threes_rating = threes_elo

    print(player)

    save_player(player)

    await interaction.followup.send(
        f"Your ratings are:  1v1 - {ones_elo}     2v2 - {twos_elo}     3v3 - {threes_elo}"

    )
# </editor-fold>

# <editor-fold desc="Submit score command">

@bot.tree.command(name="submit", description="submit scores for your match")
async def submit(interaction, match_id: str):
    await interaction.response.defer()
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()

    cur.execute("""
            UPDATE matches
            SET status = 'submitting'
            WHERE match_id = ? AND status = 'ongoing'
        """, (str(match_id),))
    claimed = cur.rowcount > 0
    print(claimed)
    conn.commit()


    '''if not claimed:
        conn.close()
        await interaction.followup.send(
            "This match is already being submitted or isn't active.", ephemeral=True
        )
        return'''

    cur.execute("SELECT player_ids FROM matches WHERE match_id = ?", (match_id,))
    ids_str = cur.fetchone()
    conn.close()
    player_ids = ids_str[0].split(" ")

    required_votes = 0
    if len(player_ids) == 6:
        required_votes = 4
    elif len(player_ids) == 4:
        required_votes = 3
    elif len(player_ids) == 2:
        required_votes = 2
    else:
        await interaction.followup.send("Error, not enough ids in the db")
        return


    for discord_id in player_ids:
        try:
            user = await bot.fetch_user(int(discord_id))
            await user.send(f"Match {match_id}: Please confirm or dispute the score")
        except discord.Forbidden:
            print(f"cant dm user: {discord_id}")
        except discord.NotFound:
            print(f"cannot find user: {discord_id}")


    await send_winner_vote_dm(match_id, player_ids = player_ids, required_votes=required_votes)
    await interaction.followup.send("Sending confirmation DMs...", ephemeral=True)
    return




# </editor-fold>


# </editor-fold>




init_db()
generate_id()
bot.run(TOKEN)