from redbot.core.bot import Red

from .pkmnchampions import PkmnChampions


async def setup(bot: Red) -> None:
    await bot.add_cog(PkmnChampions(bot))
