import random
import re
from datetime import datetime, timedelta, timezone

from arclet.alconna import Arg, Args, Alconna
from nonebot.adapters.onebot.v11 import MessageEvent, Bot
from nonebot.internal.params import ArgPlainText
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import and_, select

from ..dependency.db_access import (
    get_draw_score_cost,
    get_checkin_score_range,
    get_interest_daily_rate,
    get_or_create_user,
    set_draw_score_cost,
    set_checkin_score_range,
    set_interest_daily_rate,
)
from ..dependency.permission import ADMIN_PERMISSION
from ..dependency.rule import IS_GROUP_ENABLE
from ..dependency.timezone import (
    default_tz_day_window_utc,
    ensure_utc,
    get_timezone,
    set_timezone,
    utc_now,
)
from ..model.checkin import Checkin
from ..model.user_wallet import UserWallet

_RANGE_PATTERN = re.compile(r"^(\d+)-(\d+)$")
_QQ_PATTERN = re.compile(r"^\d{5,20}$")

checkin_cmd = on_alconna("签到", skip_for_unmatch=False)
set_checkin_score_cmd = on_alconna(
    Alconna(
        "设置签到积分",
        Args["score_range", str],
        separators="#",
    ),
    rule=IS_GROUP_ENABLE,
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
set_interest_rate_cmd = on_alconna(
    Alconna(
        "设置利率",
        Args["rate", float],
        separators="#",
    ),
    rule=IS_GROUP_ENABLE,
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
set_draw_score_cost_cmd = on_alconna(
    Alconna(
        "设置抽卡积分",
        Args["cost", int],
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
set_default_timezone_cmd = on_alconna(
    Alconna(
        "设置默认时区",
        Args["tz", int],
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
claim_interest_cmd = on_alconna("领取利息", skip_for_unmatch=False)
query_balance_cmd = on_alconna("查询余额", skip_for_unmatch=False)
deposit_cmd = on_alconna(
    Alconna(
        "存款",
        Args["amount", int],
        separators="#",
    ),
    rule=IS_GROUP_ENABLE,
    skip_for_unmatch=False,
)
withdraw_cmd = on_alconna(
    Alconna(
        "取款",
        Args["amount", int],
        separators="#",
    ),
    rule=IS_GROUP_ENABLE,
    skip_for_unmatch=False,
)
transfer_score_cmd = on_alconna(
    Alconna(
        "转让积分",
        Args(
            Arg("to_qq", str),
            Arg("amount", int),
            separators="#"
        ),
        separators="#",
    ),
    rule=IS_GROUP_ENABLE,
    skip_for_unmatch=False,
)

admin_add_score_cmd = on_alconna(
    Alconna(
        "管理加积分",
        Args(
            Arg("target_qq", str),
            Arg("amount", int),
            separators="#"
        ),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
admin_reduce_score_cmd = on_alconna(
    Alconna(
        "管理扣积分",
        Args(
            Arg("target_qq", str),
            Arg("amount", int),
            separators="#"
        ),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)


def _parse_score_range(text: str) -> tuple[int, int] | None:
    match = _RANGE_PATTERN.fullmatch(text.strip())
    if match is None:
        return None
    low, high = int(match.group(1)), int(match.group(2))
    if low <= 0 or high <= 0 or low > high:
        return None
    return low, high


def _is_valid_qq(qq: str) -> bool:
    return bool(_QQ_PATTERN.fullmatch(qq.strip()))


async def _get_or_create_wallet(session: async_scoped_session, user_id: int) -> UserWallet:
    wallet_res = await session.execute(select(UserWallet).where(UserWallet.user_id == user_id))
    wallet = wallet_res.scalar_one_or_none()
    if wallet is None:
        wallet = UserWallet(user_id=user_id, deposit=0, score=0)
        session.add(wallet)
        await session.flush()
    return wallet


@set_checkin_score_cmd.handle()
async def set_checkin_score_handle(
        session: async_scoped_session,
        score_range: Match[str],
):
    parsed = _parse_score_range(score_range.result)
    if parsed is None:
        await set_checkin_score_cmd.finish("格式错误，请使用：设置签到积分#5-10")

    low, high = parsed
    await set_checkin_score_range(session, low, high)

    await session.commit()
    await set_checkin_score_cmd.finish(f"签到积分范围已设置为 {low}-{high}")


@set_interest_rate_cmd.handle()
async def set_interest_rate_handle(
        session: async_scoped_session,
        rate: Match[float],
):
    rate_value = rate.result
    if rate_value < 0 or rate_value > 100:
        await set_interest_rate_cmd.finish("利率范围错误，请使用：设置利率#0.5（0-100，单位：%/天）")

    await set_interest_daily_rate(session, rate_value)

    await session.commit()
    await set_interest_rate_cmd.finish(f"每日利率已设置为 {rate_value}%")


@set_draw_score_cost_cmd.handle()
async def set_draw_score_cost_handle(
        session: async_scoped_session,
        cost: Match[int],
):
    parsed_cost = cost.result
    if parsed_cost <= 0:
        current = await get_draw_score_cost(session)
        await set_draw_score_cost_cmd.finish(
            "抽卡积分必须为正整数，请使用：设置抽卡积分#1\n"
            f"当前抽卡积分：{current}"
        )

    await set_draw_score_cost(session, parsed_cost)
    await session.commit()
    await set_draw_score_cost_cmd.finish(f"抽卡积分已设置为每抽 {parsed_cost} 分")


@set_default_timezone_cmd.handle()
async def set_default_timezone_handle(
        session: async_scoped_session,
        tz: Match[int],
):
    tz_offset = tz.result
    if tz_offset < -12 or tz_offset > 14:
        current_tz = await get_timezone(session)
        await set_default_timezone_cmd.finish(
            "时区格式错误，请使用整数时区偏移，例如：设置默认时区#0、设置默认时区#+8、设置默认时区#-5\n"
            f"当前默认时区：{current_tz.tzname(None)}"
        )
        return

    await set_timezone(session, tz_offset)

    tz_name = datetime.now(timezone(timedelta(hours=tz_offset)))
    await set_default_timezone_cmd.finish(f"默认时区已设置为 {tz_name}（保存值：{tz_offset}）")


@claim_interest_cmd.handle()
async def claim_interest_handle(
        session: async_scoped_session,
        event: MessageEvent,
):
    qq = event.get_user_id()
    user = await get_or_create_user(session, qq)
    wallet = await _get_or_create_wallet(session, user.id)
    if wallet.deposit <= 0:
        await claim_interest_cmd.finish("当前存款为 0，无法领取利息")

    rate = await get_interest_daily_rate(session)
    if rate <= 0:
        await claim_interest_cmd.finish("当前利率为 0，请联系管理员设置利率")

    now = utc_now()
    last_claim_at = wallet.interest_last_claim_at
    if last_claim_at is None:
        wallet.interest_last_claim_at = now
        await session.commit()
        await claim_interest_cmd.finish("首次领取已登记起算时间，请满 1 天后再领取")
        return

    last_claim_at = ensure_utc(last_claim_at)

    elapsed_days = (now - last_claim_at).days
    if elapsed_days < 1:
        await claim_interest_cmd.finish("未满 1 天，暂时无法领取利息")

    interest = int(wallet.deposit * rate * elapsed_days / 100)
    if interest <= 0:
        await claim_interest_cmd.finish("当前可领取利息为 0，请稍后再试")

    wallet.score += interest
    wallet.interest_last_claim_at = last_claim_at + timedelta(days=elapsed_days)
    await session.commit()
    await claim_interest_cmd.finish(
        f"领取成功：按 {elapsed_days} 天、{rate}%/天 计算，获得 {interest} 积分\n"
        f"当前积分：{wallet.score}"
    )


@query_balance_cmd.handle()
async def query_balance_handle(
        session: async_scoped_session,
        event: MessageEvent,
):
    user = await get_or_create_user(session, event.get_user_id())
    wallet = await _get_or_create_wallet(session, user.id)
    rate = await get_interest_daily_rate(session)
    await query_balance_cmd.finish(
        f"当前存款：{wallet.deposit}\n"
        f"当前积分：{wallet.score}（当前利率：{rate}%/天）"
    )


@deposit_cmd.handle()
async def deposit_handle(
        session: async_scoped_session,
        event: MessageEvent,
        amount: Match[int],
):
    parsed_amount = amount.result
    if parsed_amount <= 0:
        await deposit_cmd.finish("数量必须为正整数")

    user = await get_or_create_user(session, event.get_user_id())
    wallet = await _get_or_create_wallet(session, user.id)
    wallet.deposit += parsed_amount

    await session.commit()
    await deposit_cmd.finish(f"存款成功，增加 {parsed_amount}，当前存款 {wallet.deposit}")


@withdraw_cmd.handle()
async def withdraw_handle(
        session: async_scoped_session,
        event: MessageEvent,
        amount: Match[int],
):
    parsed_amount = amount.result
    if parsed_amount <= 0:
        await withdraw_cmd.finish("数量必须为正整数")

    user = await get_or_create_user(session, event.get_user_id())
    wallet = await _get_or_create_wallet(session, user.id)
    if wallet.deposit < parsed_amount:
        await withdraw_cmd.finish(f"存款不足，当前存款 {wallet.deposit}")

    wallet.deposit -= parsed_amount
    await session.commit()
    await withdraw_cmd.finish(f"取款成功，减少 {parsed_amount}，当前存款 {wallet.deposit}")


@transfer_score_cmd.handle()
async def transfer_score_prepare(
        bot: Bot,
        matcher: Matcher,
        state: T_State,
        event: MessageEvent,
        to_qq: Match[str],
        amount: Match[int],
):
    from_qq = event.get_user_id()
    target_qq = to_qq.result.strip()
    if not _is_valid_qq(target_qq):
        await matcher.finish("目标 QQ 格式错误，请使用：转让积分#123456")
    if target_qq == from_qq:
        await matcher.finish("不能给自己转让积分")
    if amount.result <= 0:
        await matcher.finish("数量必须为正整数")

    target_info = await bot.get_stranger_info(user_id=int(target_qq))
    target_nickname = target_info.get("nickname")
    await transfer_score_cmd.send(
        f"请确认：向 {target_nickname}（{target_qq}）转让 {amount.result} 积分\n"
        f"回复 确认 或 取消"
    )

    state["from_qq"] = from_qq
    state["to_qq"] = target_qq
    state["amount"] = amount.result


@transfer_score_cmd.got("confirm")
async def transfer_score_commit(
        session: async_scoped_session,
        matcher: Matcher,
        state: T_State,
        confirm: str = ArgPlainText(),
):
    confirm_text = confirm.strip()
    if confirm_text == "取消":
        await matcher.finish("已取消转让")
    if confirm_text != "确认":
        amount = state.get("amount")
        await matcher.reject(f"请回复 确认 或 取消（数量 {amount}）")
        return

    from_qq = state["from_qq"]
    to_qq = state["to_qq"]
    amount = state["amount"]

    from_user = await get_or_create_user(session, from_qq)
    to_user = await get_or_create_user(session, to_qq)
    from_wallet = await _get_or_create_wallet(session, from_user.id)
    if from_wallet.score < amount:
        await matcher.finish(f"转让失败：积分不足，当前积分 {from_wallet.score}")

    to_wallet = await _get_or_create_wallet(session, to_user.id)
    from_wallet.score -= amount
    to_wallet.score += amount

    await session.commit()
    await matcher.finish(
        f"转让成功：向 {to_qq} 转让 {amount} 积分\n"
        f"你的当前积分：{from_wallet.score}"
    )


@checkin_cmd.handle()
async def checkin_handle(
        session: async_scoped_session,
        event: MessageEvent,
):
    qq = event.get_user_id()
    user = await get_or_create_user(session, qq)

    now = utc_now()
    today_start, tomorrow_start = await default_tz_day_window_utc(session, now)

    checkin_res = await session.execute(
        select(Checkin).where(
            and_(
                Checkin.user_id == user.id,
                Checkin.checkin_date >= today_start,
                Checkin.checkin_date < tomorrow_start,
            )
        )
    )
    if checkin_res.scalar_one_or_none() is not None:
        await checkin_cmd.finish("今天已经签到过了，明天再来吧")

    low, high = await get_checkin_score_range(session)
    points = random.randint(low, high)

    wallet = await _get_or_create_wallet(session, user.id)
    wallet.score += points
    session.add(Checkin(user_id=user.id, checkin_date=now))

    await session.commit()
    await checkin_cmd.finish(f"签到成功，获得 {points} 积分，当前积分 {wallet.score}")


# 管理员操作任意用户积分
@admin_add_score_cmd.handle()
async def admin_add_score_prepare(
        session: async_scoped_session,
        matcher: Matcher,
        target_qq: Match[str],
        amount: Match[int],
):
    qq = target_qq.result.strip()
    if not _is_valid_qq(qq):
        await matcher.finish("目标 QQ 格式错误，请使用：管理加积分#123456")
    parsed_amount = amount.result
    if parsed_amount <= 0:
        await matcher.finish("数量必须为正整数")

    user = await get_or_create_user(session, qq)
    wallet = await _get_or_create_wallet(session, user.id)
    wallet.score += parsed_amount
    await session.commit()
    await matcher.finish(f"已为 {qq} 增加 {parsed_amount} 积分，当前积分 {wallet.score}")


@admin_reduce_score_cmd.handle()
async def admin_reduce_score_prepare(
        session: async_scoped_session,
        matcher: Matcher,
        target_qq: Match[str],
        amount: Match[int],
):
    qq = target_qq.result.strip()
    if not _is_valid_qq(qq):
        await matcher.finish("目标 QQ 格式错误，请使用：管理扣积分#123456")
    parsed_amount = amount.result
    if parsed_amount <= 0:
        await matcher.finish("数量必须为正整数")

    user = await get_or_create_user(session, qq)
    wallet = await _get_or_create_wallet(session, user.id)
    if wallet.score < parsed_amount:
        await matcher.finish(f"积分不足，当前积分 {wallet.score}")
    wallet.score -= parsed_amount
    await session.commit()
    await matcher.finish(f"已为 {qq} 扣除 {parsed_amount} 积分，当前积分 {wallet.score}")
