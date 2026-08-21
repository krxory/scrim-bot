import asyncio
import random

import discord
import discord.ui

from db import save_match, report_player
from models import Match
from state import ongoing_submit

# How long a captain gets to make a single pick before we auto-pick for them
TURN_SECONDS = 30


def is_valid_bo3_score(score_a, score_b):
    """A Bo3 series ends the moment either side reaches 2 wins, so a valid final
    score always has exactly one side at 2 and the other at 0 or 1."""
    if score_a < 0 or score_b < 0:
        return False
    if score_a > 2 or score_b > 2:
        return False
    if score_a != 2 and score_b != 2:
        return False  # nobody's actually won the series yet
    if score_a == 2 and score_b == 2:
        return False  # a Bo3 can't end 2-2
    return True


class ScoreModal(discord.ui.Modal, title="Submit Series Score"):
    team_a_score = discord.ui.TextInput(label="Team A wins (0-2)", max_length=1, placeholder="0, 1, or 2")
    team_b_score = discord.ui.TextInput(label="Team B wins (0-2)", max_length=1, placeholder="0, 1, or 2")

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            score_a = int(self.team_a_score.value)
            score_b = int(self.team_b_score.value)
        except ValueError:
            await interaction.response.send_message("Scores must be numbers.", ephemeral=True)
            return

        if not is_valid_bo3_score(score_a, score_b):
            await interaction.response.send_message(
                "That's not a valid Bo3 score — one team needs exactly 2 wins, the other 0 or 1.",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        await self.view.submit_score(interaction.user.id, score_a, score_b)


class ScoreSubmitView(discord.ui.View):

    def __init__(self, match_id, player_ids, required_votes, messages=None):
        super().__init__(timeout=180)
        self.match_id = match_id
        self.player_ids = [int(pid) for pid in player_ids]  # interaction.user.id is always int
        self.required_votes = required_votes
        self.messages = messages or []

        self.proposed_score = None   # (score_a, score_b) or None
        self.proposed_by = None
        self.agreements = set()

        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()

        submit_label = "Submit Score" if self.proposed_score is None else "Propose Different Score"
        submit_btn = discord.ui.Button(label=submit_label, style=discord.ButtonStyle.blurple)
        submit_btn.callback = self._submit_callback
        self.add_item(submit_btn)

        if self.proposed_score is not None:
            agree_btn = discord.ui.Button(label="Agree", style=discord.ButtonStyle.green)
            agree_btn.callback = self._agree_callback
            self.add_item(agree_btn)

    async def _submit_callback(self, interaction: discord.Interaction):
        if interaction.user.id not in self.player_ids:
            await interaction.response.send_message("You're not part of this match.", ephemeral=True)
            return
        await interaction.response.send_modal(ScoreModal(self))

    async def _agree_callback(self, interaction: discord.Interaction):
        if interaction.user.id not in self.player_ids:
            await interaction.response.send_message("You're not part of this match.", ephemeral=True)
            return
        if self.proposed_score is None:
            await interaction.response.send_message("No score has been submitted yet.", ephemeral=True)
            return

        self.agreements.add(interaction.user.id)
        await interaction.response.defer()
        await self.broadcast_update()

    async def submit_score(self, user_id, score_a, score_b):
        # a new proposal replaces the old one entirely -- stale agreement on a
        # different score shouldn't carry over
        self.proposed_score = (score_a, score_b)
        self.proposed_by = user_id
        self.agreements = {user_id}
        self._build_buttons()
        await self.broadcast_update()

    def build_embed(self, status=None):
        embed = discord.Embed(title=f"Match #{self.match_id} — Submit Score", color=discord.Color.blurple())

        if self.proposed_score is not None:
            score_a, score_b = self.proposed_score
            embed.add_field(name="Proposed Score", value=f"Team A **{score_a}** — **{score_b}** Team B", inline=False)
            embed.add_field(name="Agreements", value=f"{len(self.agreements)}/{self.required_votes}", inline=False)

        if status == "completed":
            score_a, score_b = self.proposed_score
            winner = "Team A" if score_a > score_b else "Team B"
            embed.description = f"**Confirmed: Team A {score_a} — {score_b} Team B**"
            embed.set_footer(text=f'Match complete!  Winner: {winner}')
        elif status == "canceled":
            embed.description = "**No score agreement reached — match canceled.**"
            embed.set_footer(text="Match canceled")
        elif self.proposed_score is None:
            embed.description = "No score submitted yet. Tap **Submit Score** to propose one."
            embed.set_footer(text=f"{self.required_votes} agreements needed to confirm")
        else:
            embed.description = "Tap **Agree** to confirm, or submit a different score if this is wrong."
            embed.set_footer(text=f"{self.required_votes} agreements needed to confirm")

        return embed

    async def broadcast_update(self):
        embed = self.build_embed()
        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        if len(self.agreements) >= self.required_votes:
            await self.resolve()

    async def resolve(self):
        for item in self.children:
            item.disabled = True

        score_a, score_b = self.proposed_score
        embed = self.build_embed(status="completed")
        del ongoing_submit[self.match_id]
        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        self.stop()

        from db import complete_match
        complete_match(self.match_id, score_a, score_b)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        embed = self.build_embed(status="canceled")
        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        from db import cancel_match
        cancel_match(self.match_id)

class TeamSelectView(discord.ui.View):
    def __init__(self, players, player_ids, match_id, gamemode, region, ongoing_matches, messages=None):
        super().__init__(timeout=120)
        self.players = players
        self.player_ids = player_ids
        self.match_id = match_id
        self.gamemode = gamemode
        self.region = region
        self.messages = messages or []
        self.player_selection_vote = {}
        self.vote_counts = {1:0,2:0,3:0}
        self.ongoing_matches = ongoing_matches
        if gamemode == 1:
            self.required_votes = 2
        elif gamemode == 2:
            self.required_votes = 3
        elif gamemode == 3:
            self.required_votes = 4

        if gamemode == 1:
            for item in list(self.children):
                if item.label in ("Balanced", "Captains"):
                    self.remove_item(item)
                elif item.label == "Random":
                    item.label = "Ready"


    @discord.ui.button(label="Balanced", style=discord.ButtonStyle.blurple)
    async def vote_balanced(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_vote(interaction, choice=1)

    @discord.ui.button(label="Captains", style=discord.ButtonStyle.blurple)
    async def vote_captains(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_vote(interaction, choice=2)

    @discord.ui.button(label="Random", style=discord.ButtonStyle.blurple)
    async def vote_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_vote(interaction, choice=3)

    async def record_vote(self, interaction, choice):
        user_id = interaction.user.id
        current = self.player_selection_vote.get(user_id)

        if current == choice:
            del self.player_selection_vote[user_id]
        else:
            self.player_selection_vote[user_id] = choice
            self.vote_counts[choice] += 1

        await interaction.response.defer()
        await self.broadcast_update()

    def get_votes(self):
        balanced_votes = self.vote_counts[1]
        captain_votes = self.vote_counts[2]
        random_votes = self.vote_counts[3]
        return balanced_votes, captain_votes, random_votes

    def get_winner(self):
        # 0 = no votes cast at all, 1/2/3 = Balanced/Captains/Random,
        # ties are broken with an equal-weight random pick among the tied options
        balanced_votes, captain_votes, random_votes = self.get_votes()
        counts = {1: balanced_votes, 2: captain_votes, 3: random_votes}

        top_votes = max(counts.values())
        if top_votes == 0:
            return 0

        leaders = [choice for choice, v in counts.items() if v == top_votes]
        if len(leaders) == 1:
            return leaders[0]
        return random.choice(leaders)

    async def broadcast_update(self):
        embed = self.build_embed()
        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        balanced_votes, captain_votes, random_votes = self.get_votes()
        if balanced_votes >= self.required_votes or captain_votes >= self.required_votes or random_votes >= self.required_votes:
            await self.resolve()

    def build_embed(self, status=None):
        balanced_votes, captain_votes, random_votes = self.get_votes()
        embed = discord.Embed(title=f"{self.gamemode} — {self.region}", color=discord.Color.blurple())
        embed.add_field(name="Balanced", value=str(balanced_votes), inline=True)
        embed.add_field(name="Captains", value=str(captain_votes), inline=True)
        embed.add_field(name="Random", value=str(random_votes), inline=True)


        labels = {1: "Balanced", 2: "Captains", 3: "Random"}

        if status == "resolved":
            winner = self.get_winner()
            embed.description = f"**{labels[winner]} wins!**"
            embed.set_footer(text="Vote confirmed")
        elif status == "timeout_resolved":
            winner = self.get_winner()
            embed.description = f"**Timeout reached — {labels[winner]} wins!**"
            embed.set_footer(text="Vote closed")
        elif status == "canceled":
            embed.description = "**No votes were cast — match canceled.**"
            embed.set_footer(text="Vote closed")
        else:
            embed.set_footer(text=f"{self.required_votes} votes needed to confirm")

        return embed

    async def _finalize(self, status):
        for item in self.children:
            item.disabled = True

        winner = self.get_winner()
        embed = self.build_embed(status=status)

        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        del self.ongoing_matches[self.match_id]
        self.stop()

        # local imports to avoid a circular import between views.py <-> matchmaking.py
        if winner == 1:  # Balanced
            from matchmaking import start_balanced_teams
            await start_balanced_teams(self.players, self.match_id, self.gamemode)
        elif winner == 2:  # Captains
            from matchmaking import start_captain_picks
            await start_captain_picks(self.players, self.match_id, self.gamemode)
        elif winner == 3:  # Random
            from matchmaking import start_random_teams
            await start_random_teams(self.players, self.match_id, self.gamemode)
        # winner == 0 means nobody voted -- match is canceled, nothing further to do

    async def resolve(self):
        await self._finalize(status="resolved")

    async def on_timeout(self):
        winner = self.get_winner()
        status = "canceled" if winner == 0 else "timeout_resolved"
        await self._finalize(status=status)


class CaptainSelectView(discord.ui.View):
    """
    Sent as a DM to the two team captains. Each remaining player gets a button
    showing their name + elo for the current gamemode's ratings. Captains take
    turns picking; each turn has a TURN_SECONDS window before we auto-pick a
    random remaining player for whoever's turn it is.
    """

    def __init__(self, players, match_id, gamemode, captain_a_id, captain_b_id, names, messages=None):
        super().__init__(timeout=None)  # timing is handled manually, per-turn
        self.players = players
        self.players_by_id = {p.discord_id: p for p in players}
        self.match_id = match_id
        self.gamemode = gamemode
        self.names = names  # {discord_id: display_name}

        self.captain_a_id = captain_a_id
        self.captain_b_id = captain_b_id
        self.team_a_ids = [captain_a_id]
        self.team_b_ids = [captain_b_id]
        self.remaining_ids = [
            p.discord_id for p in players if p.discord_id not in (captain_a_id, captain_b_id)
        ]

        self.current_captain_id = captain_a_id
        self.messages = messages or []

        self.turn_task = None
        self.turn_resolved = False

        self._build_buttons()

    def _rating_key(self):
        return {1: "ones_rating", 2: "twos_rating", 3: "threes_rating"}[self.gamemode]

    def _build_buttons(self):
        self.clear_items()
        for discord_id in self.remaining_ids:
            player = self.players_by_id[discord_id]
            name = self.names.get(discord_id, str(discord_id))
            label = f"{name} (1s:{player.ones_rating} 2s:{player.twos_rating} 3s:{player.threes_rating})"
            label = label[:80]  # Discord button labels cap out at 80 chars
            button = discord.ui.Button(style=discord.ButtonStyle.blurple, label=label, custom_id=str(discord_id))
            button.callback = self._make_callback(discord_id)
            self.add_item(button)

    def _make_callback(self, picked_id):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.current_captain_id:
                await interaction.response.send_message("It's not your turn to pick!", ephemeral=True)
                return
            await interaction.response.defer()
            await self._process_pick(picked_id)
        return callback

    def build_embed(self, finished=False):
        embed = discord.Embed(title=f"Match #{self.match_id} — Captain's Picks", color=discord.Color.blurple())

        team_a_names = ", ".join(self.names.get(i, str(i)) for i in self.team_a_ids) or "—"
        team_b_names = ", ".join(self.names.get(i, str(i)) for i in self.team_b_ids) or "—"
        embed.add_field(name="Team A", value=team_a_names, inline=False)
        embed.add_field(name="Team B", value=team_b_names, inline=False)

        if finished:
            embed.description = "**Draft complete!**"
            embed.set_footer(text="Teams are set")
        else:
            current_name = self.names.get(self.current_captain_id, str(self.current_captain_id))
            embed.description = f"**{current_name} is picking...**"
            embed.set_footer(text=f"{TURN_SECONDS}s per pick — tap a player below to draft them")

        return embed

    async def _process_pick(self, picked_id):
        if self.turn_resolved:
            return
        self.turn_resolved = True

        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()

        self._assign_pick(picked_id)
        await self._advance()

    async def _auto_pick(self):
        if self.turn_resolved or not self.remaining_ids:
            return
        self.turn_resolved = True

        picked_id = random.choice(self.remaining_ids)
        print(f"Captain {self.current_captain_id} timed out, auto-picking {picked_id}")

        self._assign_pick(picked_id)
        await self._advance()

    def _assign_pick(self, picked_id):
        if self.current_captain_id == self.captain_a_id:
            self.team_a_ids.append(picked_id)
        else:
            self.team_b_ids.append(picked_id)
        self.remaining_ids.remove(picked_id)

    async def _advance(self):
        team_full_size = self.gamemode

        if not self.remaining_ids or (
            len(self.team_a_ids) >= team_full_size and len(self.team_b_ids) >= team_full_size
        ):
            await self._finish_draft()
            return

        other_captain_id = self.captain_b_id if self.current_captain_id == self.captain_a_id else self.captain_a_id
        other_team = self.team_b_ids if self.current_captain_id == self.captain_a_id else self.team_a_ids

        if len(other_team) < team_full_size:
            self.current_captain_id = other_captain_id
        # else: the other captain's team is already full, so the current captain picks again

        self._build_buttons()
        embed = self.build_embed()
        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        await self.start_turn_timer()

    async def start_turn_timer(self):
        self.turn_resolved = False
        self.turn_task = asyncio.create_task(self._turn_timeout())

    async def _turn_timeout(self):
        try:
            await asyncio.sleep(TURN_SECONDS)
            await self._auto_pick()
        except asyncio.CancelledError:
            pass

    async def _finish_draft(self):
        for item in self.children:
            item.disabled = True

        embed = self.build_embed(finished=True)
        for msg in self.messages:
            try:
                await msg.edit(embed=embed, view=self)
            except discord.HTTPException:
                continue

        self.stop()

        from matchmaking import finalize_teams
        await finalize_teams(self.match_id, self.team_a_ids, self.team_b_ids, self.names)


class ReportPlayerModal(discord.ui.Modal, title="Report Player"):
    reason = discord.ui.TextInput(
        label="What happened?",
        style=discord.TextStyle.paragraph,
        max_length=500,
        placeholder="Describe the issue..."
    )

    def __init__(self, match_id, reporter_id, target_id):
        super().__init__()
        self.match_id = match_id
        self.reporter_id = reporter_id
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        report_player(reporter_id=self.reporter_id, reported_id=self.target_id, message=self.reason.value)
        await interaction.followup.send("report went through, thank you!", ephemeral=True)


class ReportSelectView(discord.ui.View):
    def __init__(self, match_id, reporter_id, candidate_ids, names):
        super().__init__(timeout=60)
        self.match_id = match_id
        self.reporter_id = reporter_id
        self.candidate_ids = candidate_ids
        self.names = names

        options = [
            discord.SelectOption(label=names.get(pid, pid), value=str(pid))
            for pid in candidate_ids
        ]

        select = discord.ui.Select(placeholder="Choose a player...", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        picked_id = interaction.data["values"][0]
        await interaction.response.send_modal(
            ReportPlayerModal(match_id=self.match_id, reporter_id=self.reporter_id, target_id=picked_id)
        )


