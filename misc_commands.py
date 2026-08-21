import sqlite3

from bot_instance import bot
from config import QUEUE_CHANNEL_ID
import discord
import asyncio

from db import report_player
from views import ReportSelectView

@bot.tree.command(name="report", description="report player from one of your matches")
async def submit(interaction, match_id: str):
    await interaction.response.defer(ephemeral=True)

    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("SELECT player_ids FROM matches WHERE match_id = ?", (match_id,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        await interaction.followup.send("Couldn't find that match, please recheck match id and try again", ephemeral=True)
        return

    player_ids = row[0].split(" ")
    if str(interaction.user.id) not in player_ids:
        await interaction.followup.send("You weren't in that match.", ephemeral=True)
        return

    others = [pid for pid in player_ids if pid != str(interaction.user.id)]

    names = {}
    for pid in others:
        try:
            user = await bot.fetch_user(int(pid))
            names[pid] = user.display_name
        except (discord.Forbidden, discord.NotFound):
            names[pid] = pid
    view = ReportSelectView(match_id=match_id, reporter_id=interaction.user.id, candidate_ids = others, names=names)
    await interaction.followup.send("Who are you reporting?", view=view, ephemeral=True)
    return