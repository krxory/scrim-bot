from bot_instance import bot
from config import TOKEN
from db import init_db
from matchmaking import generate_id

# Importing these registers their @bot.tree.command / @bot.event decorators
import events
import queue_commands
import rank_commands
import match_commands
import misc_commands


init_db()
generate_id()
bot.run(TOKEN)

