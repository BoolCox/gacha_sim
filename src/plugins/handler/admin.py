from arclet.alconna import Args, Alconna
from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import select

from ..dependency.db_access import get_or_create_user
from ..dependency.permission import ADMIN_PERMISSION, invalidate_admin_cache
from ..model.user import User

set_admin_cmd = on_alconna(
    Alconna(
        "设置管理员",
        Args["qq", int],
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)

remove_admin_cmd = on_alconna(
    Alconna(
        "删除管理员",
        Args["qq", int],
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)

list_admin_cmd = on_alconna(
    "列出管理员",
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)


def _normalize_qq(raw: str) -> str | None:
    value = raw.strip()
    if not value.isdigit():
        return None
    return value


@set_admin_cmd.handle()
async def set_admin_handle(
        session: async_scoped_session,
        qq: Match[int],
):
    target_qq = str(qq.result)

    user = await get_or_create_user(session, target_qq)
    user.is_admin = True

    await session.commit()
    invalidate_admin_cache(target_qq)
    await set_admin_cmd.finish(f"已设置管理员：{target_qq}")


@remove_admin_cmd.handle()
async def remove_admin_handle(
        session: async_scoped_session,
        qq: Match[str],
):
    target_qq = str(qq.result)

    user = await get_or_create_user(session, target_qq)
    if not user.is_admin:
        await remove_admin_cmd.finish(f"{target_qq} 不是管理员")

    user.is_admin = False
    await session.commit()
    invalidate_admin_cache(target_qq)
    await remove_admin_cmd.finish(f"已删除管理员：{target_qq}")


@list_admin_cmd.handle()
async def list_admin_handle(bot: Bot, session: async_scoped_session):
    result = await session.execute(
        select(User.qq).where(User.is_admin.is_(True)).order_by(User.qq)
    )
    qqs = [row[0] for row in result.all()]
    qqs.append(bot.config.superusers)
    if not qqs:
        await list_admin_cmd.finish("暂无管理员")

    await list_admin_cmd.finish("\n".join(qqs))
