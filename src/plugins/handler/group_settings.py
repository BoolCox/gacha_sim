from arclet.alconna import Arg, Args, Alconna, CommandMeta
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, PrivateMessageEvent
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import select

from ..dependency.db_access import get_interest_daily_rate, set_private_interaction_enabled
from ..dependency.permission import ADMIN_PERMISSION
from ..model.gacha_template import GachaTemplate
from ..model.group import Scene

open_scene = on_alconna(
    Alconna(
        "开启群",
        Args["scene_id?", int],
        meta=CommandMeta(compact=True),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)

close_scene = on_alconna(
    Alconna(
        "关闭群",
        Args["scene_id?", int],
        meta=CommandMeta(compact=True),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)

set_scene_default_template = on_alconna(
    Alconna(
        "设置默认模板",
        Args(
            Arg("template_name", str),
            Arg("scene_id?", int),
            separators="#",
        ),
        meta=CommandMeta(compact=True),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)

show_scene_settings = on_alconna(
    Alconna(
        "查看配置",
        Args["scene_id?", int],
        meta=CommandMeta(compact=True),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)

set_private_interaction = on_alconna(
    Alconna(
        "设置私聊互动",
        Args["enabled", str],
        meta=CommandMeta(compact=True),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)


@set_private_interaction.handle()
async def set_private_interaction_handle(
        session: async_scoped_session,
        enabled: Match[str],
):
    if enabled.result not in {"开", "关"}:
        await set_private_interaction.finish("参数错误，请使用 设置私聊互动#开 或 设置私聊互动#关")
        return

    await set_private_interaction_enabled(session, enabled.result)
    await session.commit()
    action = "开启" if enabled.result == "开" else "关闭"
    await set_private_interaction.finish(f"已{action}私聊互动")


@open_scene.handle()
async def open_scene_handle(
        session: async_scoped_session,
        event: MessageEvent,
        scene_id: Match[int],
):
    if isinstance(event, PrivateMessageEvent):
        if not scene_id.available:
            await open_scene.finish("私聊场景请以 开启群#<群号> 的格式指定群")
        sid = str(scene_id.result)
    elif isinstance(event, GroupMessageEvent):
        sid = str(event.group_id)
    else:
        await open_scene.finish("暂不支持该场景")
        return

    result = await session.execute(select(Scene).where(Scene.scene_id == sid))
    group = result.scalar_one_or_none()

    if group is None:
        session.add(Scene(scene_id=sid, enabled=True))
    else:
        group.enabled = True

    await session.commit()
    await open_scene.finish(f"场景{sid}已开启")


@close_scene.handle()
async def close_group_handle(
        session: async_scoped_session,
        event: MessageEvent,
        scene_id: Match[str],
):
    if isinstance(event, PrivateMessageEvent):
        if not scene_id.available:
            await close_scene.finish("私聊场景请以 关闭群#<群号> 的格式指定群")
        sid = str(scene_id.result)
    elif isinstance(event, GroupMessageEvent):
        sid = str(event.group_id)
    else:
        await close_scene.finish("暂不支持该场景")
        return

    result = await session.execute(select(Scene).where(Scene.scene_id == sid))
    scene = result.scalar_one_or_none()
    if scene is None:
        session.add(Scene(scene_id=sid, enabled=False))
    else:
        scene.enabled = False

    await session.commit()
    await close_scene.finish(f"场景{sid}已关闭")


@set_scene_default_template.handle()
async def set_scene_default_template_handle(
        session: async_scoped_session,
        event: MessageEvent,
        template_name: Match[str],
        scene_id: Match[str],
):
    if isinstance(event, PrivateMessageEvent):
        if not scene_id.available:
            await set_scene_default_template.finish("私聊场景请以 设置默认模板#<模板名>#<群号> 的格式指定群")
        sid = str(scene_id.result)
    elif isinstance(event, GroupMessageEvent):
        sid = str(event.group_id)
    else:
        await set_scene_default_template.finish("暂不支持该场景")
        return

    template_result = await session.execute(
        select(GachaTemplate).where(GachaTemplate.name == template_name.result)
    )
    if template_result.scalar_one_or_none() is None:
        await set_scene_default_template.finish(f"模板「{template_name.result}」不存在")

    group_result = await session.execute(select(Scene).where(Scene.scene_id == sid))
    scene = group_result.scalar_one_or_none()
    if scene is None:
        session.add(Scene(scene_id=sid, default_template_name=template_name.result))
    else:
        scene.default_template_name = template_name.result

    await session.commit()
    await set_scene_default_template.finish(f"群{sid}默认模板已设置为「{template_name.result}」")


@show_scene_settings.handle()
async def show_group_settings_handle(
        session: async_scoped_session,
        event: MessageEvent,
        scene_id: Match[int],
):
    if isinstance(event, PrivateMessageEvent):
        if not scene_id.available:
            await show_scene_settings.finish("私聊场景请以 查看群设置#<群号> 的格式指定群")
            return
        sid = str(scene_id.result)
    elif isinstance(event, GroupMessageEvent):
        sid = str(event.group_id)
    else:
        await show_scene_settings.finish("暂不支持该场景")
        return

    result = await session.execute(select(Scene).where(Scene.scene_id == sid))
    scene = result.scalar_one_or_none()
    if scene is None:
        await show_scene_settings.finish(f"群{sid}暂无设置")
        return

    interest_rate = await get_interest_daily_rate(session)
    template_name = scene.default_template_name or "未设置"
    status = "开启" if scene.enabled else "关闭"
    await show_scene_settings.finish(
        f"群{sid}设置：\n"
        f"功能状态：{status}\n"
        f"默认模板：{template_name}\n"
        f"当前利率：{interest_rate:g}"
    )
