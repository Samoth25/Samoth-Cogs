import asyncio
import random
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .views import BattleWaitingLobbyView, RegistrationView


class PkmnChampions(commands.Cog):
    """Cog de combats Pokémon aléatoires pour Red-DiscordBot."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=9371625480, force_registration=True
        )
        self.config.register_guild(
            battle_channels=[],       # liste des channel IDs éligibles
            battle_interval=60,       # minutes entre deux combats aléatoires
            battle_duration=30,       # minutes avant annulation automatique
            battle_formats=["Singles", "Doubles", "VGC"],
            mod_roles=[],             # rôles mentionnés en cas de litige
        )
        # guild_id -> dict de l'état du combat en cours
        self.active_battles: dict[int, dict] = {}
        # guild_id -> task de la boucle automatique
        self.battle_tasks: dict[int, asyncio.Task] = {}

    def cog_unload(self) -> None:
        for task in self.battle_tasks.values():
            task.cancel()
        for battle in self.active_battles.values():
            if battle.get("cancel_task"):
                battle["cancel_task"].cancel()

    # ── Constructeurs d'embeds ───────────────────────────────────────────────────

    def _embed_registration(self, battle: dict) -> discord.Embed:
        p1 = f"<@{battle['player1_id']}>" if battle["player1_id"] else "*En attente...*"
        p2 = f"<@{battle['player2_id']}>" if battle["player2_id"] else "*En attente...*"
        embed = discord.Embed(
            title="⚔️ Combat Pokémon — Inscription ouverte !",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Format", value=f"`{battle['format']}`", inline=True)
        embed.add_field(name="Durée max", value=f"{battle['duration']} min", inline=True)
        embed.add_field(name="Joueur 1", value=p1, inline=True)
        embed.add_field(name="Joueur 2", value=p2, inline=True)
        embed.set_footer(
            text=f"Ce combat sera annulé si deux joueurs ne s'inscrivent pas dans {battle['duration']} minutes."
        )
        return embed

    def _embed_active(self, battle: dict) -> discord.Embed:
        p1 = f"<@{battle['player1_id']}>"
        p2 = f"<@{battle['player2_id']}>"
        if battle["lobby_code"] is None:
            status = "⏳ En attente du code lobby de " + p1
        else:
            status = "✅ Code lobby partagé — Bonne chance !"
        embed = discord.Embed(
            title="⚔️ Combat en cours !",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Format", value=f"`{battle['format']}`", inline=True)
        embed.add_field(name="Combat", value=f"{p1} **VS** {p2}", inline=False)
        embed.add_field(name="Statut", value=status, inline=False)
        embed.set_footer(
            text="Une fois le combat terminé, cliquez sur 'J'ai gagné !' ou 'J'ai perdu...'."
        )
        return embed

    def _embed_result(self, battle: dict, winner_id: int) -> discord.Embed:
        loser_id = (
            battle["player2_id"] if winner_id == battle["player1_id"] else battle["player1_id"]
        )
        embed = discord.Embed(
            title="🏆 Combat terminé !",
            color=discord.Color.green(),
        )
        embed.add_field(name="Format", value=f"`{battle['format']}`", inline=True)
        embed.add_field(name="🥇 Vainqueur", value=f"<@{winner_id}>", inline=True)
        embed.add_field(name="💀 Vaincu", value=f"<@{loser_id}>", inline=True)
        return embed

    def _embed_dispute(self, battle: dict) -> discord.Embed:
        embed = discord.Embed(
            title="⚠️ Litige détecté !",
            description=(
                "Les deux joueurs ont déclaré le même résultat. "
                "Un modérateur doit intervenir pour trancher."
            ),
            color=discord.Color.red(),
        )
        embed.add_field(name="Format", value=f"`{battle['format']}`", inline=True)
        embed.add_field(name="Joueur 1", value=f"<@{battle['player1_id']}>", inline=True)
        embed.add_field(name="Joueur 2", value=f"<@{battle['player2_id']}>", inline=True)
        return embed

    def _embed_cancelled(self, battle: dict) -> discord.Embed:
        embed = discord.Embed(
            title="❌ Combat annulé",
            description="Le délai est écoulé sans que deux joueurs se soient inscrits ou aient terminé le combat.",
            color=discord.Color.dark_gray(),
        )
        embed.add_field(name="Format", value=f"`{battle['format']}`", inline=True)
        return embed

    # ── Cycle de vie d'un combat ─────────────────────────────────────────────────

    async def post_random_battle(self, guild: discord.Guild) -> bool:
        """Poste un embed de combat aléatoire. Retourne True si réussi."""
        if guild.id in self.active_battles:
            return False

        cfg = await self.config.guild(guild).all()

        if not cfg["battle_channels"] or not cfg["battle_formats"]:
            return False

        channel = guild.get_channel(random.choice(cfg["battle_channels"]))
        if not channel:
            return False

        battle: dict = {
            "guild_id": guild.id,
            "message": None,
            "format": random.choice(cfg["battle_formats"]),
            "duration": cfg["battle_duration"],
            "player1_id": None,
            "player2_id": None,
            "status": "waiting",
            "lobby_code": None,
            "player1_result": None,
            "player2_result": None,
            "cancel_task": None,
        }

        msg = await channel.send(
            embed=self._embed_registration(battle),
            view=RegistrationView(self, battle),
        )
        battle["message"] = msg
        battle["cancel_task"] = asyncio.create_task(
            self._auto_cancel(guild.id, battle, cfg["battle_duration"] * 60)
        )
        self.active_battles[guild.id] = battle
        return True

    async def _auto_cancel(
        self, guild_id: int, battle: dict, delay: float
    ) -> None:
        """Annule automatiquement un combat après le délai imparti."""
        await asyncio.sleep(delay)
        if battle["status"] in ("waiting", "active"):
            battle["status"] = "cancelled"
            try:
                await battle["message"].edit(
                    embed=self._embed_cancelled(battle), view=None
                )
            except discord.NotFound:
                pass
            self.active_battles.pop(guild_id, None)

    async def resolve_battle(self, battle: dict) -> None:
        """Résout le combat une fois que les deux joueurs ont soumis leur résultat."""
        if battle.get("cancel_task"):
            battle["cancel_task"].cancel()

        p1_won = battle["player1_result"] == "win"
        p2_won = battle["player2_result"] == "win"

        if p1_won != p2_won:
            # Les résultats concordent
            winner_id = battle["player1_id"] if p1_won else battle["player2_id"]
            battle["status"] = "finished"
            await battle["message"].edit(
                embed=self._embed_result(battle, winner_id), view=None
            )
        else:
            # Litige : les deux ont déclaré gagner ou les deux ont déclaré perdre
            battle["status"] = "dispute"
            await battle["message"].edit(
                embed=self._embed_dispute(battle), view=None
            )
            mod_roles = await self.config.guild_from_id(battle["guild_id"]).mod_roles()
            mentions = " ".join(f"<@&{r}>" for r in mod_roles)
            if mentions:
                await battle["message"].reply(
                    f"{mentions} ⚠️ Un litige a été détecté, votre intervention est requise !"
                )

        self.active_battles.pop(battle["guild_id"], None)

    # ── Boucle automatique ───────────────────────────────────────────────────────

    async def _battle_loop(self, guild: discord.Guild) -> None:
        """Boucle qui poste des combats à intervalle régulier."""
        while True:
            interval = await self.config.guild(guild).battle_interval()
            await asyncio.sleep(interval * 60)
            await self.post_random_battle(guild)

    # ── Commandes admin ──────────────────────────────────────────────────────────

    @commands.group(name="pkmnset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def pkmnset(self, ctx: commands.Context) -> None:
        """Paramètres de PkmnChampions."""

    @pkmnset.command(name="channel")
    async def pkmnset_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Ajoute ou retire un channel des combats aléatoires."""
        async with self.config.guild(ctx.guild).battle_channels() as channels:
            if channel.id in channels:
                channels.remove(channel.id)
                await ctx.send(f"✅ {channel.mention} retiré des channels de combat.")
            else:
                channels.append(channel.id)
                await ctx.send(f"✅ {channel.mention} ajouté aux channels de combat.")

    @pkmnset.command(name="interval")
    async def pkmnset_interval(self, ctx: commands.Context, minutes: int) -> None:
        """Définit l'intervalle entre les combats aléatoires (en minutes)."""
        if minutes < 1:
            return await ctx.send("❌ L'intervalle doit être d'au moins 1 minute.")
        await self.config.guild(ctx.guild).battle_interval.set(minutes)
        await ctx.send(f"✅ Intervalle défini à **{minutes}** minutes.")

    @pkmnset.command(name="duration")
    async def pkmnset_duration(self, ctx: commands.Context, minutes: int) -> None:
        """Définit la durée max d'un combat avant annulation automatique (en minutes)."""
        if minutes < 1:
            return await ctx.send("❌ La durée doit être d'au moins 1 minute.")
        await self.config.guild(ctx.guild).battle_duration.set(minutes)
        await ctx.send(f"✅ Durée définie à **{minutes}** minutes.")

    @pkmnset.command(name="addformat")
    async def pkmnset_addformat(
        self, ctx: commands.Context, *, format_name: str
    ) -> None:
        """Ajoute un format de combat."""
        async with self.config.guild(ctx.guild).battle_formats() as formats:
            if format_name in formats:
                return await ctx.send("❌ Ce format existe déjà.")
            formats.append(format_name)
        await ctx.send(f"✅ Format `{format_name}` ajouté.")

    @pkmnset.command(name="removeformat")
    async def pkmnset_removeformat(
        self, ctx: commands.Context, *, format_name: str
    ) -> None:
        """Retire un format de combat."""
        async with self.config.guild(ctx.guild).battle_formats() as formats:
            if format_name not in formats:
                return await ctx.send("❌ Ce format n'existe pas.")
            formats.remove(format_name)
        await ctx.send(f"✅ Format `{format_name}` retiré.")

    @pkmnset.command(name="formats")
    async def pkmnset_formats(self, ctx: commands.Context) -> None:
        """Liste les formats de combat disponibles."""
        formats = await self.config.guild(ctx.guild).battle_formats()
        if not formats:
            return await ctx.send("Aucun format configuré.")
        await ctx.send(
            "**Formats disponibles :**\n" + "\n".join(f"• `{f}`" for f in formats)
        )

    @pkmnset.command(name="modrole")
    async def pkmnset_modrole(
        self, ctx: commands.Context, role: discord.Role
    ) -> None:
        """Ajoute ou retire un rôle modérateur pour les litiges."""
        async with self.config.guild(ctx.guild).mod_roles() as roles:
            if role.id in roles:
                roles.remove(role.id)
                await ctx.send(f"✅ {role.mention} retiré des rôles modérateurs.")
            else:
                roles.append(role.id)
                await ctx.send(f"✅ {role.mention} ajouté aux rôles modérateurs.")

    @pkmnset.command(name="settings")
    async def pkmnset_settings(self, ctx: commands.Context) -> None:
        """Affiche tous les paramètres actuels."""
        cfg = await self.config.guild(ctx.guild).all()

        channels = [f"<#{c}>" for c in cfg["battle_channels"]] or ["*Aucun*"]
        formats = [f"`{f}`" for f in cfg["battle_formats"]] or ["*Aucun*"]
        mod_roles = [f"<@&{r}>" for r in cfg["mod_roles"]] or ["*Aucun*"]

        task = self.battle_tasks.get(ctx.guild.id)
        loop_status = "✅ Active" if task and not task.done() else "❌ Inactive"

        active = self.active_battles.get(ctx.guild.id)
        battle_status = (
            f"Combat en cours (format : `{active['format']}`)"
            if active
            else "*Aucun combat actif*"
        )

        embed = discord.Embed(
            title="⚙️ Paramètres PkmnChampions", color=discord.Color.blurple()
        )
        embed.add_field(name="Channels", value="\n".join(channels), inline=False)
        embed.add_field(name="Intervalle", value=f"{cfg['battle_interval']} min", inline=True)
        embed.add_field(name="Durée max", value=f"{cfg['battle_duration']} min", inline=True)
        embed.add_field(name="Formats", value=" · ".join(formats), inline=False)
        embed.add_field(name="Rôles modérateurs", value=" ".join(mod_roles), inline=False)
        embed.add_field(name="Boucle automatique", value=loop_status, inline=True)
        embed.add_field(name="Statut", value=battle_status, inline=False)
        await ctx.send(embed=embed)

    # ── Contrôle de la boucle ────────────────────────────────────────────────────

    @commands.command(name="pkmnstart")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def pkmnstart(self, ctx: commands.Context) -> None:
        """Démarre la boucle de combats aléatoires automatiques."""
        task = self.battle_tasks.get(ctx.guild.id)
        if task and not task.done():
            return await ctx.send("❌ La boucle est déjà active.")
        self.battle_tasks[ctx.guild.id] = asyncio.create_task(
            self._battle_loop(ctx.guild)
        )
        interval = await self.config.guild(ctx.guild).battle_interval()
        await ctx.send(
            f"✅ Boucle démarrée. Premier combat dans **{interval}** minutes."
        )

    @commands.command(name="pkmnstop")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def pkmnstop(self, ctx: commands.Context) -> None:
        """Arrête la boucle de combats aléatoires automatiques."""
        task = self.battle_tasks.pop(ctx.guild.id, None)
        if task:
            task.cancel()
            await ctx.send("✅ Boucle arrêtée.")
        else:
            await ctx.send("❌ La boucle n'est pas active.")

    @commands.command(name="pkmnbattle")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def pkmnbattle(self, ctx: commands.Context) -> None:
        """Poste immédiatement un combat aléatoire (test / déclenchement manuel)."""
        if ctx.guild.id in self.active_battles:
            return await ctx.send(
                "❌ Un combat est déjà en cours. Attendez qu'il se termine."
            )
        success = await self.post_random_battle(ctx.guild)
        if not success:
            await ctx.send(
                "❌ Impossible de poster un combat. "
                "Vérifiez les paramètres avec `[p]pkmnset settings`."
            )
