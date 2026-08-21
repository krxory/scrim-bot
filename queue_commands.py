import time

from discord import app_commands

from bot_instance import bot
from db import get_player, is_player_in_match
from state import queues, ongoing_vote, ongoing_submit

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

    key = (queues[region.value][gamemode.value])

    if region.value not in queues or gamemode.value not in queues[region.value]:
        await interaction.followup.send("Invalid region/gamemode combo!")
        return

    in_match = is_player_in_match(discord_id=interaction.user.id)
    in_queue = any(interaction.user.id == p.discord_id for region_queues in queues.values() for queue in region_queues.values() for p in queue)
    in_vote = any(interaction.user.id == p for vote in ongoing_vote.values() for p in vote)
    in_submit = any(interaction.user.id == p for vote in ongoing_submit.values() for p in vote)

    if in_match == True:
        await interaction.followup.send("You are already in an ongoing match")
        return
    elif in_queue == True:
        await interaction.followup.send("You are already in the queue")
        return
    elif in_vote == True:
        await interaction.followup.send("You are currently voting, check your dms!")
        return
    elif in_submit == True:
        await interaction.followup.send("You are currently submitting a series, check your dms!")
        return
    else:
        pass

    rating_key = {1: player.ones_rating, 2:player.twos_rating, 3:player.threes_rating}


    try: key.append((player.discord_id, rating_key[gamemode.value], time.time()))
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
            if p[0] == player.discord_id:
                queues[key].remove(p)
                found = True
                break
    if found:
        await interaction.followup.send("successfully left the queue!")
    else:
        await interaction.followup.send("couldn't find you in the queue!")
    print(queues)

# </editor-fold>
