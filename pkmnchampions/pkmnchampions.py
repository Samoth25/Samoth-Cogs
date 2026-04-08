from redbot.core import commands
from redbot.core.bot import Red


class PkmnChampions(commands.Cog):
    """A Pokemon Champions cog."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
