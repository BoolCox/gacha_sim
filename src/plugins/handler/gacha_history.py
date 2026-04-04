from arclet.alconna import Alconna, Args
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import desc, func, select

from ..dependency.rule import IS_GROUP_ENABLE
from ..dependency.timezone import ensure_utc, get_timezone
from ..model.gacha_banner import GachaBannerPool
from ..model.gacha_drop_record import GachaDropRecord
from ..model.gacha_item import GachaItem
from ..model.gacha_template import GachaTemplate
from ..model.user import User

history_cmd = on_alconna(
    Alconna(
        "抽卡记录",
        Args["num?", int],
        separators="#"
    ),
    rule=IS_GROUP_ENABLE,
    skip_for_unmatch=False
)

stats_cmd = on_alconna("抽卡统计", rule=IS_GROUP_ENABLE, skip_for_unmatch=False)


@history_cmd.handle()
async def history_handle(
        session: async_scoped_session,
        event: MessageEvent,
        num: Match[int],
):
    tz = await get_timezone(session)
    user_id = event.get_user_id()
    if not num.available:
        n = 30
    elif not (1 <= num.result <= 50):
        await history_cmd.finish("请输入 1~50 的整数，例如：抽卡记录#30")
        return
    else:
        n = num.result

    user_res = await session.execute(select(User).where(User.qq == user_id))
    user = user_res.scalar_one_or_none()
    if user is None:
        await history_cmd.finish("暂无抽卡记录")
        return

    rows = await session.execute(
        select(
            GachaDropRecord.draw_date,
            GachaDropRecord.banner_pool_id,
            GachaDropRecord.item_id,
            GachaDropRecord.score_cost,
            GachaBannerPool.name,
            GachaItem.name,
        )
        .join(GachaBannerPool, GachaBannerPool.id == GachaDropRecord.banner_pool_id)
        .join(GachaItem, GachaItem.id == GachaDropRecord.item_id)
        .where(GachaDropRecord.user_id == user.id)
        .order_by(desc(GachaDropRecord.draw_date), desc(GachaDropRecord.id))
        .limit(n)
    )
    records = rows.all()
    if not records:
        await history_cmd.finish("暂无抽卡记录")

    lines: list[str] = []
    for r in records:
        local_dt = ensure_utc(r.draw_date).astimezone(tz)
        lines.append(f"{local_dt.strftime('%Y-%m-%d %H:%M:%S')} | {r.name} | {r[5]} | 消耗 {r.score_cost} 积分")
    await history_cmd.finish(f"最近抽卡记录（时区：{tz.tzname(None)}）：\n" + "\n".join(lines))


@stats_cmd.handle()
async def stats_handle(
        session: async_scoped_session,
        event: MessageEvent,
):
    qq = event.get_user_id()

    user_res = await session.execute(select(User).where(User.qq == qq))
    user = user_res.scalar_one_or_none()
    if user is None:
        await stats_cmd.finish("暂无抽卡统计")
        return

    group_rows = await session.execute(
        select(
            GachaDropRecord.banner_pool_id,
            GachaBannerPool.name.label("banner_name"),
            GachaTemplate.name.label("template_name"),
            func.count().label("cnt"),
        )
        .join(GachaBannerPool, GachaBannerPool.id == GachaDropRecord.banner_pool_id)
        .join(GachaTemplate, GachaTemplate.id == GachaDropRecord.template_id)
        .where(GachaDropRecord.user_id == user.id)
        .group_by(
            GachaDropRecord.banner_pool_id,
            GachaBannerPool.name,
            GachaTemplate.name,
        )
        .order_by(desc("cnt"))
    )
    groups = group_rows.all()
    if not groups:
        await stats_cmd.finish("暂无抽卡统计")

    blocks: list[str] = []
    for g in groups:
        item_rows = await session.execute(
            select(
                GachaDropRecord.item_id,
                GachaItem.name,
                func.count().label("cnt"),
            )
            .join(GachaItem, GachaItem.id == GachaDropRecord.item_id)
            .where(
                GachaDropRecord.user_id == user.id,
                GachaDropRecord.banner_pool_id == g.banner_pool_id,
            )
            .group_by(GachaDropRecord.item_id, GachaItem.name)
            .order_by(desc("cnt"), GachaDropRecord.item_id)
        )
        items = item_rows.all()
        top10 = items[:10]
        rest = sum(x.cnt for x in items[10:])

        lines = [f"  - {name}(id={item_id}) x {cnt}" for item_id, name, cnt in top10]
        if rest > 0:
            lines.append(f"  - 其余合计 x {rest}")
        blocks.append(
            f"模板「{g.template_name}」的卡池「{g.banner_name}」总掉落 {g.cnt}：\n"
            + "\n".join(lines)
        )

    await stats_cmd.finish("你的全局抽卡统计：\n" + "\n\n".join(blocks))
