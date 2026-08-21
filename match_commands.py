import sqlite3

import discord

from bot_instance import bot
from matchmaking import send_score_submit_dm
from state import ongoing_submit


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


    if not claimed:
        conn.close()
        await interaction.followup.send(
            "This match is already being submitted or isn't active.", ephemeral=True
        )
        return

    cur.execute("SELECT player_ids FROM matches WHERE match_id = ?", (match_id,))
    ids_str = cur.fetchone()
    conn.close()
    player_ids = ids_str[0].split(" ")
    player_ids = [int(pid) for pid in player_ids]
    print(f"Player ids ongoing submit: {player_ids}")

    ongoing_submit[match_id] = player_ids
    print(ongoing_submit)


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


    await send_score_submit_dm(match_id, player_ids = player_ids, required_votes=required_votes)
    await interaction.followup.send("Sending confirmation DMs...", ephemeral=True)
    return


# </editor-fold>