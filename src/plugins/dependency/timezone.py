from datetime import datetime, timedelta, timezone

from nonebot_plugin_orm import async_scoped_session
from .db_access import get_default_timezone_offset, set_default_timezone_offset

DATETIME_INPUT_FORMAT = "%Y-%m-%d %H:%M"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def get_timezone(session: async_scoped_session) -> timezone:
    offset = await get_default_timezone_offset(session)
    return timezone(timedelta(hours=offset))


async def parse_user_datetime_to_utc(session: async_scoped_session, value: str) -> datetime:
    db_timezone = await get_timezone(session)

    local_dt = (
        datetime
        .strptime(value.strip(), DATETIME_INPUT_FORMAT)
        .replace(tzinfo=db_timezone)
    )
    return ensure_utc(local_dt)


async def default_tz_day_window_utc(
        session: async_scoped_session,
        now: datetime,
) -> tuple[datetime, datetime]:
    current_utc = ensure_utc(now)
    db_timezone = await get_timezone(session)

    local_now = current_utc.astimezone(db_timezone)
    local_day_start = datetime(local_now.year, local_now.month, local_now.day, tzinfo=db_timezone)
    local_day_end = local_day_start + timedelta(days=1)
    return ensure_utc(local_day_start), ensure_utc(local_day_end)


async def set_timezone(session: async_scoped_session, offset: int) -> None:
    await set_default_timezone_offset(session, offset)
    await session.commit()
