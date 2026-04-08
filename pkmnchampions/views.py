from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ui

if TYPE_CHECKING:
    from .pkmnchampions import PkmnChampions


class LobbyCodeModal(ui.Modal, title="Entrer le code lobby"):
    code = ui.TextInput(
        label="Code lobby",
        placeholder="Ex: AB1234",
        min_length=1,
        max_length=20,
    )

    def __init__(self, cog: "PkmnChampions", battle: dict) -> None:
        super().__init__()
        self.cog = cog
        self.battle = battle

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.battle["lobby_code"] = self.code.value

        await interaction.response.send_message(
            f"✅ Code lobby enregistré ! <@{self.battle['player2_id']}> peut maintenant le récupérer via le bouton prévu.",
            ephemeral=True,
        )

        embed = self.cog._embed_active(self.battle)
        view = BattleInProgressView(self.cog, self.battle)
        await self.battle["message"].edit(embed=embed, view=view)


class RegistrationView(ui.View):
    def __init__(self, cog: "PkmnChampions", battle: dict) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.battle = battle
        self._refresh()

    def _refresh(self) -> None:
        """Reconstruit les boutons selon l'état actuel de l'inscription."""
        self.clear_items()

        join_btn = ui.Button(
            label="Participer", style=discord.ButtonStyle.success, emoji="⚔️"
        )
        join_btn.callback = self._join
        self.add_item(join_btn)

        if self.battle["player1_id"] is not None:
            cancel_btn = ui.Button(
                label="Annuler mon inscription",
                style=discord.ButtonStyle.secondary,
                emoji="❌",
            )
            cancel_btn.callback = self._cancel
            self.add_item(cancel_btn)

    async def _join(self, interaction: discord.Interaction) -> None:
        battle = self.battle
        user_id = interaction.user.id

        if battle["status"] != "waiting":
            return await interaction.response.send_message(
                "Ce combat n'est plus disponible.", ephemeral=True
            )

        if user_id in (battle["player1_id"], battle["player2_id"]):
            return await interaction.response.send_message(
                "Vous êtes déjà inscrit pour ce combat !", ephemeral=True
            )

        if battle["player1_id"] is None:
            battle["player1_id"] = user_id
            self._refresh()
            await interaction.response.edit_message(
                embed=self.cog._embed_registration(battle), view=self
            )

        elif battle["player2_id"] is None:
            battle["player2_id"] = user_id
            battle["status"] = "active"
            await interaction.response.edit_message(
                embed=self.cog._embed_active(battle),
                view=BattleWaitingLobbyView(self.cog, battle),
            )

        else:
            await interaction.response.send_message(
                "Ce combat est déjà complet !", ephemeral=True
            )

    async def _cancel(self, interaction: discord.Interaction) -> None:
        battle = self.battle
        user_id = interaction.user.id

        if user_id != battle["player1_id"]:
            return await interaction.response.send_message(
                "Vous n'êtes pas inscrit à ce combat.", ephemeral=True
            )

        battle["player1_id"] = None
        self._refresh()
        await interaction.response.edit_message(
            embed=self.cog._embed_registration(battle), view=self
        )
        await interaction.followup.send("✅ Inscription annulée.", ephemeral=True)


class BattleWaitingLobbyView(ui.View):
    """Phase 2 : les deux joueurs sont inscrits, le joueur 1 doit entrer son code lobby."""

    def __init__(self, cog: "PkmnChampions", battle: dict) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.battle = battle

    @ui.button(label="Entrer le code lobby 🎮", style=discord.ButtonStyle.primary)
    async def enter_code(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        if interaction.user.id != self.battle["player1_id"]:
            return await interaction.response.send_message(
                "Seul le joueur 1 peut entrer le code lobby.", ephemeral=True
            )
        await interaction.response.send_modal(LobbyCodeModal(self.cog, self.battle))


class BattleInProgressView(ui.View):
    """Phase 3 : code lobby partagé, en attente des résultats des deux joueurs."""

    def __init__(self, cog: "PkmnChampions", battle: dict) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.battle = battle

    @ui.button(label="Voir le code lobby 🔑", style=discord.ButtonStyle.secondary)
    async def view_code(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        if interaction.user.id != self.battle["player2_id"]:
            return await interaction.response.send_message(
                "Ce bouton est réservé au joueur 2.", ephemeral=True
            )
        await interaction.response.send_message(
            f"🔑 Code lobby : **`{self.battle['lobby_code']}`**",
            ephemeral=True,
        )

    @ui.button(label="J'ai gagné ! 🏆", style=discord.ButtonStyle.success)
    async def i_won(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        await self._submit_result(interaction, "win")

    @ui.button(label="J'ai perdu... 💀", style=discord.ButtonStyle.danger)
    async def i_lost(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        await self._submit_result(interaction, "loss")

    async def _submit_result(
        self, interaction: discord.Interaction, result: str
    ) -> None:
        user_id = interaction.user.id
        battle = self.battle

        if user_id not in (battle["player1_id"], battle["player2_id"]):
            return await interaction.response.send_message(
                "Vous ne participez pas à ce combat.", ephemeral=True
            )

        if user_id == battle["player1_id"]:
            if battle["player1_result"] is not None:
                return await interaction.response.send_message(
                    "Vous avez déjà soumis votre résultat.", ephemeral=True
                )
            battle["player1_result"] = result
        else:
            if battle["player2_result"] is not None:
                return await interaction.response.send_message(
                    "Vous avez déjà soumis votre résultat.", ephemeral=True
                )
            battle["player2_result"] = result

        await interaction.response.send_message(
            "✅ Résultat enregistré ! En attente du résultat de l'autre joueur...",
            ephemeral=True,
        )

        if battle["player1_result"] is not None and battle["player2_result"] is not None:
            await self.cog.resolve_battle(battle)
