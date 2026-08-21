import datetime
import sqlite3

from models import Player


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

    cur.execute("""
                CREATE TABLE IF NOT EXISTS reported_players (
                    discord_id INTEGER PRIMARY KEY,
                    reports INTEGER NOT NULL DEFAULT 0
                )
            """)

    cur.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reported_id INTEGER NOT NULL,
                reporter_id INTEGER NOT NULL,
                message TEXT,
                time_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    conn.commit()
    conn.close()

def report_player(reported_id, reporter_id, message):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO reported_players (discord_id, reports)
        VALUES (?, 1)
        ON CONFLICT(discord_id) DO UPDATE SET
            reports = reports + 1
    """, (reported_id,))

    cur.execute("""
        INSERT INTO reports (reported_id, reporter_id, message)
        VALUES (?, ?, ?)
        """, (reported_id, reporter_id, message))

    conn.commit()
    conn.close()
    print("report went through")



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
    print("saving player")

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
    print("getting player")
    return player

def save_match(match):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("""
            INSERT INTO matches (match_id, gamemode, player_ids, team_a_ids, team_b_ids, status, time_created)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                gamemode = excluded.gamemode,
                player_ids = excluded.player_ids,
                status = excluded.status,
                time_created = excluded.time_created
        """, (match.match_id, match.gamemode, match.player_ids, match.team_a_ids, match.team_b_ids, match.status, match.time_created))
    conn.commit()
    conn.close()
    print("saving match before completion")

def complete_match(match_id, score_a, score_b):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("""
        UPDATE matches
        SET status = 'completed', score_a = ?, score_b = ?, time_completed = ?
        WHERE match_id = ? AND status IN ('ongoing', 'submitting')
    """, (score_a, score_b, datetime.datetime.now().isoformat(), str(match_id)))
    conn.commit()
    conn.close()
    print("completing match")

def cancel_match(match_id):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("""
        UPDATE matches
        SET status = 'canceled'
        WHERE match_id = ? AND status IN ('ongoing', 'submitting')
    """, (str(match_id),))
    conn.commit()
    conn.close()
    print("cancel match")

def is_player_in_match(discord_id):
    conn = sqlite3.connect("scrim.db")
    cur = conn.cursor()
    cur.execute("SELECT player_ids FROM matches WHERE status = 'ongoing'")
    rows = cur.fetchall()
    conn.close()
    print("checking if player is match")

    for (player_ids,) in rows:
        ids = player_ids.split(" ")
        if str(discord_id) in ids:
            return True
    return False