from bot_instance import bot
from db import save_player, get_player
from models import Player
from tracker import scrape_tracker, format_link


# <editor-fold desc="Rank check command">
@bot.tree.command(name="rank-check", description="submit your tracker to verify your mmr")
async def rank_check(interaction, tracker_url: str):
    await interaction.response.defer()
    try:
        player = get_player(interaction.user.id)
        if player is not None:
            await interaction.followup.send("You have already gotten your rank!", ephemeral=True)
            return
        else:
            pass
    except Exception as e:
        print(e)
        await interaction.followup.send("Error", ephemeral=True)
        return


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
