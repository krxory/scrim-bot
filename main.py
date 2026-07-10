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
    def __init__(self, match_id, gamemode, time_created, player_ids, status="ongoing",
                 score_a=None, score_b=None, time_completed=None):
        self.match_id = match_id
        self.gamemode = gamemode
        self.time_created = datetime.datetime.now()
        self.player_ids = player_ids
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

target_names = {
    "Ranked Duel 1v1": "ones",
    "Ranked Doubles 2v2": "twos",
    "Ranked Standard 3v3": "threes",
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
    id = generate_id()
    mentions = " ".join(f"<@{p.discord_id}>" for p in players)
    player_ids = " ".join(str(p.discord_id) for p in players)
    print(player_ids)
    time = datetime.datetime.now().isoformat()
    status = "ongoing"
    match = Match(match_id=id, gamemode=gamemode, time_created=time, player_ids=player_ids, status=status)
    save_match(match)
    await channel.send(f"Match found! {gamemode} V {gamemode} in {region}\n"
                       f"ID: {id}\n"
                       f"{mentions}")

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
        """, (match_id,))
    claimed = cur.rowcount > 0
    conn.commit()
    conn.close()

    if not claimed:
        conn.close()
        await interaction.followup.send(
            "This match is already being submitted or isn't active.", ephemeral=True
        )
        return

    cur.execute("SELECT player_ids FROM matches WHERE match_id = ?", (match_id,))
    ids_str = cur.fetchone().replace(" ", )
    ids = ids_str.strip(" ")
    for id in ids:
        try:
            user = await bot.fetch_user(int(id))
            await user.send(f"Match {match_id}: Please confirm or dispute the score")
        except discord.Forbidden:
            print(f"cant dm user: {id}")
        except discord.NotFound:
            print(f"cannot find user: {id}")
    conn.close()
    await interaction.followup.send("Sending confirmation DMs...", ephemeral=True)
    return




# </editor-fold>


# </editor-fold>




init_db()
generate_id()
bot.run(TOKEN)