from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, PrivateMessageEvent
from nonebot.internal.rule import Rule
from nonebot_plugin_orm import get_session
from sqlalchemy import select

from ..dependency.db_access import get_private_interaction_enabled
from ..model.group import Scene


async def is_enabled(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        scene_id = event.group_id
    elif isinstance(event, PrivateMessageEvent):
        async with get_session() as session:
            return await get_private_interaction_enabled(session)
    else:
        return False

    async with get_session() as session:

        result = await session.execute(
            select(Scene.enabled).where(Scene.scene_id == scene_id)
        )
        enabled = result.scalar_one_or_none()
        return bool(enabled)


IS_SCENE_ENABLE = Rule(is_enabled)
