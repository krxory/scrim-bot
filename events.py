from bot_instance import bot

from matchmaking import Matchmaker

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

    print(f"Logging in as {bot.user}")
    await bot.add_cog(Matchmaker(bot))


@bot.tree.command(name="ping")
async def ping(interaction):
    print("Ping command received")
    await interaction.response.send_message("Pong!")
