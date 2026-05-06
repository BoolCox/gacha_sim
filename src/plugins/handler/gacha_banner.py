from datetime import datetime

from arclet.alconna import Arg, Args, Alconna, CommandMeta
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, PrivateMessageEvent
from nonebot.internal.params import ArgPlainText
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_orm import async_scoped_session

from ..dependencies.enum_typy import SceneType
from ..dependencies.permission import ADMIN_PERMISSION
from ..dependencies.rule import IS_SCENE_ENABLE
from ..dependencies.timezone import get_timezone, parse_user_datetime_to_utc, utc_now
from ..service.gacha_banner import (
    CommitBannerRunParams,
    assert_pool_not_running_now,
    commit_banner_run as commit_banner_run_service,
    draw_item,
    list_running_banners_in_group,
    load_template_and_pool,
    parse_rate_up_text,
)

create_banner = on_alconna(
    Alconna(
        "创建卡池",
        Args(
            Arg("template_name", str),
            Arg("banner_name", str),
            Arg("description?", str),
            separators="#",
        ),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)

open_rerun = on_alconna(
    Alconna(
        "开启复刻",
        Args(
            Arg("template_name", str),
            Arg("banner_name", str),
            separators="#",
        ),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)

list_running_banner = on_alconna(
    Alconna(
        "查看开放卡池",
        meta=CommandMeta(compact=True),
        separators="#",
    ),
    rule=IS_SCENE_ENABLE,
    skip_for_unmatch=False,
)

draw_once = on_alconna(
    Alconna(
        "抽卡",
        Args(
            Arg("arg1", str),
            Arg("arg2?", str),
            Arg("arg3?", str),
            separators="#",
        ),
        separators="#",
    ),
    rule=IS_SCENE_ENABLE,
    skip_for_unmatch=False,
)


@create_banner.handle()
async def create_banner_prepare(
        session: async_scoped_session,
        state: T_State,
        template_name: Match[str],
        banner_name: Match[str],
        description: Match[str],
):
    # 查找 name 对应模板和卡池
    template, pool = await load_template_and_pool(
        session=session,
        template_name=template_name.result,
        banner_name=banner_name.result,
    )
    if template is None:
        await create_banner.finish(f"模板「{template_name.result}」不存在")
        return

    if pool is not None:
        await create_banner.finish(
            f"模板「{template_name.result}」下已存在同名卡池「{banner_name.result}」，"
            f"请使用 开启复刻#{template_name.result}#{banner_name.result}"
        )
        return

    state["template_name"] = template_name.result
    state["template_id"] = template.id
    state["banner_name"] = banner_name.result
    state["description"] = description.result if description.available else None
    state["action"] = "create"


@open_rerun.handle()
async def open_rerun_prepare(
        session: async_scoped_session,
        state: T_State,
        template_name: Match[str],
        banner_name: Match[str],
):
    template, pool = await load_template_and_pool(
        session=session,
        template_name=template_name.result,
        banner_name=banner_name.result,
    )
    if template is None:
        await open_rerun.finish(f"模板「{template_name.result}」不存在")
        return
    if pool is None:
        await open_rerun.finish(
            f"模板「{template_name.result}」下不存在卡池「{banner_name.result}」，请先使用 创建卡池"
        )
        return

    try:
        await assert_pool_not_running_now(session=session, pool_id=pool.id, now=utc_now())
    except ValueError as err:
        await open_rerun.finish(f"卡池「{banner_name.result}」{err}")
        return

    state["template_name"] = template_name.result
    state["template_id"] = template.id
    state["banner_name"] = banner_name.result
    state["description"] = pool.description
    state["action"] = "rerun"
    state["pool_id"] = pool.id


@create_banner.got(
    "start_at",
    prompt="请输入开启时间（格式：YYYY-MM-DD HH:MM，例如：2026-04-01 10:00）",
)
@open_rerun.got(
    "start_at",
    prompt="请输入开启时间（格式：YYYY-MM-DD HH:MM，例如：2026-04-01 10:00）",
)
async def collect_start_at(
        session: async_scoped_session,
        matcher: Matcher,
        state: T_State,
        start_at: str = ArgPlainText(),
):
    try:
        utc_dt = await parse_user_datetime_to_utc(session, start_at)
    except ValueError:
        await matcher.reject(
            f"开启时间格式错误，请使用 YYYY-MM-DD HH:MM"
        )
        return
    state["start_at"] = utc_dt


@create_banner.got(
    "end_at",
    prompt="请输入结束时间（格式：YYYY-MM-DD HH:MM；输入 无 表示永久开放/常驻）",
)
@open_rerun.got(
    "end_at",
    prompt="请输入结束时间（格式：YYYY-MM-DD HH:MM；输入 无 表示永久开放/常驻）",
)
async def collect_end_at(
        session: async_scoped_session,
        matcher: Matcher,
        state: T_State,
        end_at: str = ArgPlainText(),
):
    start_at = state["start_at"]

    if end_at == "无":
        parsed_end_at = None
    else:
        try:
            utc_dt = await parse_user_datetime_to_utc(session, end_at)
        except ValueError:
            await matcher.reject(
                f"结束时间格式错误，请使用 YYYY-MM-DD HH:MM，或输入 无"
            )
            return
        if utc_dt <= start_at:
            await matcher.reject("结束时间必须晚于开启时间")
            return
        parsed_end_at = utc_dt

    state["end_at"] = parsed_end_at

    # 复刻流程仅需输入时间，不再询问 UP 配置。
    if state.get("action") == "rerun":
        await _commit_banner_run_with_rate_up_text(
            session=session,
            state=state,
            matcher=matcher,
            rate_up_text="无",
        )
        return


async def _commit_banner_run_with_rate_up_text(
        session: async_scoped_session,
        state: T_State,
        matcher: Matcher,
        rate_up_text: str,
):
    template_name: str = state["template_name"]
    template_id: int = state["template_id"]
    banner_name: str = state["banner_name"]
    description: str | None = state.get("description")
    start_at: datetime = state["start_at"]
    end_at: datetime | None = state["end_at"]
    action: str = state["action"]

    try:
        rate_up_cfg_by_name = parse_rate_up_text(rate_up_text)
    except ValueError as err:
        await matcher.reject(f"UP 配置错误：{err}")
        return

    pool_id: int | None = None
    pool_id_raw = state.get("pool_id")
    if pool_id_raw is not None:
        if isinstance(pool_id_raw, int):
            pool_id = pool_id_raw
        elif isinstance(pool_id_raw, str):
            try:
                pool_id = int(pool_id_raw)
            except ValueError:
                await matcher.finish("未找到要复刻的卡池，请重新执行命令")
                return
        else:
            await matcher.finish("未找到要复刻的卡池，请重新执行命令")
            return
    params = CommitBannerRunParams(
        template_name=template_name,
        template_id=template_id,
        banner_name=banner_name,
        description=description,
        start_at=start_at,
        end_at=end_at,
        action=action,
        pool_id=pool_id,
    )

    try:
        message = await commit_banner_run_service(
            session=session,
            params=params,
            rate_up_cfg_by_name=rate_up_cfg_by_name,
        )
    except ValueError as err:
        text = str(err)
        if text.startswith("时间区间与"):
            await matcher.finish(f"卡池「{banner_name}」{text}")
            return
        await matcher.finish(text)
        return

    await matcher.finish(message)


@create_banner.got(
    "rate_up_text",
    prompt=(
            "请输入 UP 配置（每行：稀有度#up_share#卡片名1,卡片名2），\n"
            "示例：SSR#50#刻晴,莫娜\nSR#70#香菱\n"
            "输入 无 表示不配置 UP"
    ),
)
async def commit_banner_run(
        session: async_scoped_session,
        state: T_State,
        matcher: Matcher,
        rate_up_text: str = ArgPlainText(),
):
    await _commit_banner_run_with_rate_up_text(
        session=session,
        state=state,
        matcher=matcher,
        rate_up_text=rate_up_text,
    )


def _parse_draw_args(
        arg1: Match[str],
        arg2: Match[str],
        arg3: Match[str],
) -> tuple[str | None, str, int]:
    first = arg1.result.strip()
    if not first:
        raise ValueError("抽卡参数错误：卡池名不能为空")

    if not arg2.available:
        return None, first, 1

    second = arg2.result.strip()
    if not second:
        raise ValueError("抽卡参数错误：第二个参数不能为空")

    if not arg3.available:
        if second == "十连":
            # 兼容旧语法：抽卡#<卡池名>#十连
            return None, first, 10
        # 新语法：抽卡#<模板名>#<卡池名>
        return first, second, 1

    third = arg3.result.strip()
    if third != "十连":
        raise ValueError("抽卡参数错误：第三个参数仅支持 十连")

    # 新语法：抽卡#<模板名>#<卡池名>#十连
    return first, second, 10


@draw_once.handle()
async def draw_once_handle(
        session: async_scoped_session,
        event: MessageEvent,
        arg1: Match[str],
        arg2: Match[str],
        arg3: Match[str],
):
    if isinstance(event, GroupMessageEvent):
        scene_type = SceneType.GROUP
        scene_id: str | None = str(event.group_id)
        user_id = event.get_user_id()
    elif isinstance(event, PrivateMessageEvent):
        scene_type = SceneType.PRIVATE
        scene_id = None
        user_id = event.get_user_id()
    else:
        await draw_once.finish("暂不支持该场景的抽卡")
        return

    try:
        template_name, banner_name, draw_count = _parse_draw_args(arg1, arg2, arg3)
        if scene_type == SceneType.PRIVATE and template_name is None:
            await draw_once.finish("私聊抽卡请使用 抽卡#<模板名>#<卡池名>[#十连]")
            return

        results = await draw_item(
            session=session,
            scene_type=scene_type,
            scene_id=scene_id,
            user_id=user_id,
            banner_name=banner_name,
            now=utc_now(),
            draw_count=draw_count,
            template_name=template_name,
        )
    except ValueError as err:
        text = str(err)
        if text.startswith(("模板稀有度权重异常", "目标稀有度", "UP 配置异常")):
            await draw_once.finish(f"卡池配置异常：{text}")
            return
        await draw_once.finish(text)
        return

    if draw_count == 1:
        result = results[0]
        description_text = result.item_description.strip() if result.item_description else "无"
        await draw_once.finish(
            f"抽卡结果：{result.item_name}\n"
            f"稀有度：{result.rarity_name}\n"
            f"描述：{description_text}\n"
            f"模板：{result.template_name} | 卡池：{result.pool_name}"
        )
        return

    lines = [
        f"{idx}. {result.item_name}（{result.rarity_name}） | 描述：{result.item_description.strip() if result.item_description else '无'}"
        for idx, result in enumerate(results, start=1)
    ]
    head = f"模板：{results[0].template_name} | 卡池：{results[0].pool_name}"
    await draw_once.finish("十连结果：\n" + head + "\n" + "\n".join(lines))


@list_running_banner.handle()
async def list_running_banner_handle(
        session: async_scoped_session,
        event: MessageEvent,
):
    if not isinstance(event, GroupMessageEvent):
        await list_running_banner.finish("请在群聊中使用此命令")
        return

    gid = str(event.group_id)
    now = utc_now()
    display_tz = await get_timezone(session)
    display_tz_name = display_tz.tzname(None) or "UTC+00:00"

    try:
        template_name, lines = await list_running_banners_in_group(
            session=session,
            scene_id=gid,
            now=now,
        )
    except ValueError as err:
        await list_running_banner.finish(str(err))
        return

    await list_running_banner.finish(
        f"模板「{template_name}」运行中的 卡池（时区：{display_tz_name}）：\n" + "\n".join(lines)
    )
