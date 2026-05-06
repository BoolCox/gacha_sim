import asyncio
from time import monotonic

from nonebot import Bot
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.internal.permission import Permission
from nonebot_plugin_orm import get_session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..model.user import User

_ADMIN_CACHE_TTL_SECONDS = 30.0
_ADMIN_CACHE_ERROR_TTL_SECONDS = 2.0
_admin_cache: dict[str, tuple[bool, float]] = {}
_admin_cache_lock = asyncio.Lock()


def invalidate_admin_cache(qq: str | None = None) -> None:
    if qq is None:
        _admin_cache.clear()
        return
    _admin_cache.pop(qq, None)


async def _get_admin_flag(user_id: str) -> bool:
    now = monotonic()
    cached = _admin_cache.get(user_id)
    if cached is not None and cached[1] > now:
        return cached[0]

    async with _admin_cache_lock:
        cached = _admin_cache.get(user_id)
        now = monotonic()
        if cached is not None and cached[1] > now:
            return cached[0]

        try:
            async with get_session() as session:
                result = await session.execute(select(User.is_admin).where(User.qq == user_id))
                is_admin = bool(result.scalar_one_or_none())
            ttl = _ADMIN_CACHE_TTL_SECONDS
        except SQLAlchemyError:
            # Fail closed and set short TTL to avoid a thundering herd during DB pressure.
            is_admin = False
            ttl = _ADMIN_CACHE_ERROR_TTL_SECONDS

        _admin_cache[user_id] = (is_admin, now + ttl)
        return is_admin


async def _is_superuser_or_admin(
        bot: Bot,
        event: MessageEvent,
) -> bool:
    user_id = event.get_user_id()
    if user_id in {str(x) for x in bot.config.superusers}:
        return True

    return await _get_admin_flag(user_id)


ADMIN_PERMISSION = Permission(_is_superuser_or_admin)
