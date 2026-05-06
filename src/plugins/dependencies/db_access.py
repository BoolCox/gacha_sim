import re

from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..model.config import Config
from ..model.group import Scene
from ..model.user import User

SessionLike = async_scoped_session | AsyncSession

DEFAULT_TIMEZONE_KEY = "default_timezone"
CHECKIN_RANGE_KEY = "checkin_score_range"
INTEREST_RATE_KEY = "interest_daily_rate"
DRAW_SCORE_COST_KEY = "draw_score_cost"
PRIVATE_INTERACTION_ENABLED_KEY = "private_interaction_enabled"

FALLBACK_TIMEZONE_OFFSET = 8
FALLBACK_CHECKIN_RANGE = (5, 10)
FALLBACK_INTEREST_RATE = 0.0
FALLBACK_DRAW_SCORE_COST = 1

_CHECKIN_RANGE_PATTERN = re.compile(r"^(\d+)-(\d+)$")


async def get_or_create_scene(session: async_scoped_session, scene_id: str) -> Scene:
    result = await session.execute(
        select(Scene).where(Scene.scene_id == scene_id)
    )
    scene = result.scalar_one_or_none()
    if scene is None:
        scene = Scene(scene_id=scene_id)
        session.add(scene)
        await session.flush()
    return scene


async def get_or_create_user(session: async_scoped_session, qq: str) -> User:
    user_result = await session.execute(select(User).where(User.qq == qq))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(qq=qq)
        session.add(user)
        await session.flush()
    return user


async def get_config_by_key(session: SessionLike, key: str) -> Config | None:
    return (
        await session.execute(
            select(Config).where(Config.key == key),
        )
    ).scalar_one_or_none()


async def set_config_by_key(session: async_scoped_session, key: str, value: str) -> None:
    result = await session.get(Config, key)
    if result:
        result.value = value
    else:
        session.add(Config(key=key, value=value))


async def get_default_timezone_offset(session: SessionLike) -> int:
    config = await get_config_by_key(session, DEFAULT_TIMEZONE_KEY)
    if config is None:
        return FALLBACK_TIMEZONE_OFFSET
    try:
        return int(config.value)
    except ValueError:
        return FALLBACK_TIMEZONE_OFFSET


async def set_default_timezone_offset(session: async_scoped_session, offset: int) -> None:
    await set_config_by_key(session, DEFAULT_TIMEZONE_KEY, str(offset))


async def get_checkin_score_range(session: SessionLike) -> tuple[int, int]:
    config = await get_config_by_key(session, CHECKIN_RANGE_KEY)
    if config is None:
        return FALLBACK_CHECKIN_RANGE

    match = _CHECKIN_RANGE_PATTERN.fullmatch(config.value.strip())
    if match is None:
        return FALLBACK_CHECKIN_RANGE

    low = int(match.group(1))
    high = int(match.group(2))
    if low <= 0 or high <= 0 or low > high:
        return FALLBACK_CHECKIN_RANGE
    return low, high


async def set_checkin_score_range(session: async_scoped_session, low: int, high: int) -> None:
    await set_config_by_key(session, CHECKIN_RANGE_KEY, f"{low}-{high}")


async def get_interest_daily_rate(session: SessionLike) -> float:
    config = await get_config_by_key(session, INTEREST_RATE_KEY)
    if config is None:
        return FALLBACK_INTEREST_RATE
    try:
        rate = float(config.value)
    except ValueError:
        return FALLBACK_INTEREST_RATE
    return rate if rate >= 0 else FALLBACK_INTEREST_RATE


async def set_interest_daily_rate(session: async_scoped_session, rate: float) -> None:
    await set_config_by_key(session, INTEREST_RATE_KEY, str(rate))


async def get_draw_score_cost(session: SessionLike) -> int:
    config = await get_config_by_key(session, DRAW_SCORE_COST_KEY)
    if config is None:
        return FALLBACK_DRAW_SCORE_COST
    try:
        cost = int(config.value)
    except ValueError:
        return FALLBACK_DRAW_SCORE_COST
    return cost if cost > 0 else FALLBACK_DRAW_SCORE_COST


async def set_draw_score_cost(session: async_scoped_session, cost: int) -> None:
    await set_config_by_key(session, DRAW_SCORE_COST_KEY, str(cost))


async def get_private_interaction_enabled(session: SessionLike) -> bool:
    config = await get_config_by_key(session, PRIVATE_INTERACTION_ENABLED_KEY)
    return config is not None and config.value == "开"


async def set_private_interaction_enabled(
        session: async_scoped_session,
        enabled: str,
) -> None:
    await set_config_by_key(session, PRIVATE_INTERACTION_ENABLED_KEY, enabled)
