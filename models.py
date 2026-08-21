import datetime
import sqlite3


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
