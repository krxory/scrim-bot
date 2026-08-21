import asyncio
import random
import string
import time
from datetime import datetime

import discord
from discord.ext import tasks, commands

from bot_instance import bot
from config import QUEUE_CHANNEL_ID
from db import save_match
from state import queues, ongoing_vote
from views import CaptainSelectView, ScoreSubmitView, TeamSelectView
from models import Match


class Matchmaker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.matchmaking_loop.start()

    # This built-in function triggers automatically if you unload the cog
    async def cog_unload(self):
        self.matchmaking_loop.cancel()


    # This decorator tells the bot to wait exactly 5 seconds between loop runs
    @tasks.loop(seconds=7.0)
    async def matchmaking_loop(self):
        await bot.wait_until_ready()
        for region in queues:
            for gamemode in queues[region]:
                current_queue = queues[region][gamemode]
                anchors_by_gap = {}
                for player in current_queue:
                    gap = player[1] // 150
                    print(gap)
                    value = (player[0], player[1], player[2])
                    if gap not in anchors_by_gap:
                        anchors_by_gap[gap] = value
                    else:
                        if player[2] < anchors_by_gap[gap][2]:
                            anchors_by_gap[gap] = value
                        print(anchors_by_gap)
                for anchor in anchors_by_gap:
                    anchor_range = 50
                    time_passed = time.time() - anchor[2]
                    bonus = min(time_passed * 2, 150)
                    anchor_range += bonus
                    mmr_min = anchor[1] - anchor_range//2
                    mmr_max = anchor[1] + anchor_range//2
                    anchor_range_tuple = (mmr_min, mmr_max)













async def start_match(players, region, gamemode):
    match_id = generate_id()
    player_ids = [p.discord_id for p in players]
    print(f"Player ids ongoing vote: {player_ids}")
    ongoing_vote[match_id] = player_ids
    print(ongoing_vote)
    view = TeamSelectView(players=players, player_ids=player_ids, match_id=match_id, gamemode=gamemode, ongoing_matches=ongoing_vote, region=region)

    for discord_id in player_ids:
        try:
            user = await bot.fetch_user(int(discord_id))
            embed = view.build_embed()
            msg = await user.send(embed=embed, view=view)
            view.messages.append(msg)
        except discord.Forbidden:
            print(f"User: {discord_id} might have dms off cannot find them")
        except discord.NotFound:
            print(f"Couldnt find user: {discord_id}")



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

async def send_score_submit_dm(match_id, player_ids, required_votes):
    view = ScoreSubmitView(match_id, player_ids, required_votes)

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


async def fetch_names(players):
    """Look up display names for a list of Player objects, so views/DMs can show
    something readable instead of raw discord ids."""
    names = {}
    for p in players:
        try:
            user = await bot.fetch_user(int(p.discord_id))
            names[p.discord_id] = user.display_name
        except (discord.Forbidden, discord.NotFound):
            names[p.discord_id] = str(p.discord_id)
    return names


def generate_match_name():
    return "SCRIM-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))


def generate_match_password():
    return "".join(random.choices(string.ascii_letters + string.digits, k=6))


async def start_captain_picks(players, match_id, gamemode):
    captain_a, captain_b = random.sample(players, k=2)
    names = await fetch_names(players)

    if gamemode == 1:
        await finalize_teams(match_id, [captain_a.discord_id], [captain_b.discord_id], names, gamemode)
        return

    view = CaptainSelectView(
        players=players,
        match_id=match_id,
        gamemode=gamemode,
        captain_a_id=captain_a.discord_id,
        captain_b_id=captain_b.discord_id,
        names=names,
    )

    for captain_id in (captain_a.discord_id, captain_b.discord_id):
        try:
            user = await bot.fetch_user(int(captain_id))
            embed = view.build_embed()
            msg = await user.send(embed=embed, view=view)
            view.messages.append(msg)
        except discord.Forbidden:
            print(f"cant dm user: {captain_id}, dms may be disabled")
        except discord.NotFound:
            print(f"couldnt find user: {captain_id}")

    await view.start_turn_timer()


async def start_balanced_teams(players, match_id, gamemode):
    rating_key = {1: "ones_rating", 2: "twos_rating", 3: "threes_rating"}[gamemode]
    sorted_players = sorted(players, key=lambda p: getattr(p, rating_key), reverse=True)

    team_a, team_b = [], []
    for i, player in enumerate(sorted_players):
        (team_a if i % 2 == 0 else team_b).append(player)

    names = await fetch_names(players)
    await finalize_teams(match_id, [p.discord_id for p in team_a], [p.discord_id for p in team_b], names, gamemode)


async def start_random_teams(players, match_id, gamemode):
    shuffled = players[:]
    random.shuffle(shuffled)
    half = len(shuffled) // 2
    team_a, team_b = shuffled[:half], shuffled[half:]

    names = await fetch_names(players)
    await finalize_teams(match_id, [p.discord_id for p in team_a], [p.discord_id for p in team_b], names, gamemode)


async def finalize_teams(match_id, team_a_ids, team_b_ids, names, gamemode):
    match_name = generate_match_name()
    match_password = generate_match_password()
    player_ids = team_a_ids + team_b_ids
    player_ids_match = " ".join(str(i) for i in team_a_ids + team_b_ids)
    team_a_ids_match = " ".join(str(i) for i in team_a_ids)
    team_b_ids_match = " ".join(str(i) for i in team_b_ids)

    # Team A's captain runs the lobby -- they get a different DM than everyone else
    host_id = team_a_ids[0]
    match = Match(match_id= match_id, gamemode=gamemode, time_created=datetime.now(), team_a_ids=team_a_ids_match, team_b_ids=team_b_ids_match, player_ids=player_ids_match)



    for discord_id in team_a_ids + team_b_ids:
        team_label = "Team A" if discord_id in team_a_ids else "Team B"
        try:
            user = await bot.fetch_user(int(discord_id))
            if discord_id == host_id:
                await user.send(
                    f"Match id: #{match_id}: You're on **{team_label}**.\n"
                    f"You're hosting this match! Please create a private match named "
                    f"**{match_name}** with password **{match_password}**, then invite the other players once it's up."
                )
            else:
                await user.send(
                    f"Match {match_id}: You're on **{team_label}**.\n"
                    f"Join the match named **{match_name}** with password **{match_password}**."
                )
        except discord.Forbidden:
            print(f"cant dm user: {discord_id}, dms may be disabled")
        except discord.NotFound:
            print(f"couldnt find user: {discord_id}")

    save_match(match)
    # TODO: persist match_name/password and the final team_a_ids/team_b_ids to the matches table