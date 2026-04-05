import random
from dataclasses import dataclass
from datetime import datetime

from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from ..dependency.db_access import get_draw_score_cost, get_or_create_scene, get_or_create_user
from ..dependency.enum_typy import SceneType
from ..dependency.timezone import ensure_utc, get_timezone
from ..model.gacha_banner import (
    GachaBannerPool,
    GachaBannerRun,
    GachaBannerRunRate,
    GachaBannerRunRateItem,
)
from ..model.gacha_drop_record import GachaDropRecord
from ..model.gacha_item import GachaItem
from ..model.gacha_template import GachaRarity, GachaTemplate
from ..model.user_wallet import UserWallet

RateUpCfgByName = dict[str, tuple[int, list[str]]]
RateUpCfgById = dict[str, tuple[int, list[int]]]


@dataclass(frozen=True)
class CommitBannerRunParams:
    template_name: str
    template_id: int
    banner_name: str
    description: str | None
    start_at: datetime
    end_at: datetime | None
    action: str
    pool_id: int | None = None


@dataclass(frozen=True)
class DrawResult:
    item_name: str
    rarity_name: str
    item_description: str | None
    template_name: str
    pool_name: str


def parse_rate_up_text(value: str) -> RateUpCfgByName | None:
    raw = value.strip()
    if raw.lower() in {"无", "none", "null", "n"}:
        return None

    cfg: RateUpCfgByName = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("#", 2)
        if len(parts) != 3:
            raise ValueError(f"格式错误：{line!r}，应为 稀有度#up_share#卡片名1,卡片名2")

        rarity_name = parts[0].strip()
        up_share_text = parts[1].strip()
        item_names_text = parts[2].replace("，", ",").strip()

        if not rarity_name:
            raise ValueError("稀有度不能为空")
        if rarity_name in cfg:
            raise ValueError(f"稀有度 {rarity_name} 重复")
        if not up_share_text.isdigit():
            raise ValueError(f"up_share 必须是整数：{up_share_text!r}")

        up_share = int(up_share_text)
        if not 1 <= up_share <= 100:
            raise ValueError(f"稀有度 {rarity_name} 的 up_share 必须在 1-100")

        item_names = [token.strip() for token in item_names_text.split(",") if token.strip()]
        if not item_names:
            raise ValueError(f"稀有度 {rarity_name} 的卡片名列表不能为空")

        cfg[rarity_name] = (up_share, item_names)

    if not cfg:
        raise ValueError("未提供有效的 UP 配置")

    return cfg


async def load_template_and_pool(
        session: async_scoped_session,
        template_name: str,
        banner_name: str,
) -> tuple[GachaTemplate | None, GachaBannerPool | None]:
    template_result = await session.execute(
        select(GachaTemplate).where(GachaTemplate.name == template_name)
    )
    template = template_result.scalar_one_or_none()
    if template is None:
        return None, None

    pool_result = await session.execute(
        select(GachaBannerPool).where(
            GachaBannerPool.template_id == template.id,
            GachaBannerPool.name == banner_name,
        )
    )
    return template, pool_result.scalar_one_or_none()


async def assert_pool_not_running_now(
        session: async_scoped_session,
        pool_id: int,
        now: datetime,
) -> None:
    now = ensure_utc(now)

    result = await session.execute(
        select(GachaBannerRun)
        .where(GachaBannerRun.banner_pool_id == pool_id)
        .order_by(GachaBannerRun.start_at.desc(), GachaBannerRun.id.desc())
    )
    runs = result.scalars().all()

    for run in runs:
        run_start = ensure_utc(run.start_at)
        run_end = None if run.end_at is None else ensure_utc(run.end_at)
        if run_start <= now and (run_end is None or run_end > now):
            raise ValueError(f"当前卡池正在运行（run_id={run.id}），请等待结束后再开启复刻")


async def commit_banner_run(
        session: async_scoped_session,
        params: CommitBannerRunParams,
        rate_up_cfg_by_name: RateUpCfgByName | None,
) -> str:
    try:
        pool_id: int
        if params.action == "create":
            pool = GachaBannerPool(
                template_id=params.template_id,
                name=params.banner_name,
                description=params.description,
            )
            session.add(pool)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                raise ValueError(f"模板「{params.template_name}」下已存在同名卡池「{params.banner_name}」")
            assert pool.id is not None
            pool_id = pool.id
        else:
            if params.pool_id is None:
                raise ValueError("未找到要复刻的卡池，请重新执行命令")
            pool_id = params.pool_id

        await _assert_no_overlapping_run(
            session=session,
            pool_id=pool_id,
            start_at=params.start_at,
            end_at=params.end_at,
        )

        rate_up_cfg = await _resolve_rate_up_cfg_item_ids(
            session=session,
            template_id=params.template_id,
            template_name=params.template_name,
            rate_up_cfg=rate_up_cfg_by_name,
        )

        await _validate_drawability_preconditions(
            session=session,
            template_id=params.template_id,
            template_name=params.template_name,
            rate_up_cfg=rate_up_cfg,
        )

        run = GachaBannerRun(
            banner_pool_id=pool_id,
            start_at=params.start_at,
            end_at=params.end_at,
        )
        session.add(run)
        await session.flush()

        _persist_rate_up_cfg(session=session, run_id=run.id, rate_up_cfg=rate_up_cfg)

        await session.commit()
        return await _format_create_banner_success_message(
            session=session,
            banner_name=params.banner_name,
            template_name=params.template_name,
            run_id=run.id,
            start_at=params.start_at,
            end_at=params.end_at,
            action_text="创建成功" if params.action == "create" else "复刻开启成功",
        )
    except ValueError:
        await session.rollback()
        raise


async def draw_item(
        session: async_scoped_session,
        scene_type: SceneType,
        scene_id: str | None,
        user_id: str,
        banner_name: str,
        now: datetime,
        draw_count: int,
        template_name: str | None = None,
) -> list[DrawResult]:
    now = ensure_utc(now)
    resolved_template_name = template_name.strip() if template_name is not None else None
    if not resolved_template_name:
        if scene_id is None:
            raise ValueError("私聊抽卡请使用 抽卡#<模板名>#<卡池名>[#十连]")
        group = await get_or_create_scene(session, scene_id)
        if group.default_template_name is None:
            raise ValueError(f"未设置默认模板，请联系管理员使用 设置默认模板#<模板名> 指令设置启用的模板")
        resolved_template_name = group.default_template_name

    template, pool, run = await _resolve_running_run(
        session=session,
        template_name=resolved_template_name,
        banner_name=banner_name,
        now=now,
    )

    rarity_result = await session.execute(
        select(GachaRarity).where(GachaRarity.template_id == template.id)
    )
    rarities: list[GachaRarity] = list(rarity_result.scalars().all())

    rarity_item_result = await session.execute(
        select(GachaItem).where(
            GachaItem.template_id == template.id,
            GachaItem.rarity_name.in_([rarity.name for rarity in rarities]),
        )
    )
    all_items = rarity_item_result.scalars().all()
    items_by_rarity: dict[str, list[GachaItem]] = {}
    for item in all_items:
        items_by_rarity.setdefault(item.rarity_name, []).append(item)

    up_rate_result = await session.execute(
        select(GachaBannerRunRate).where(GachaBannerRunRate.run_id == run.id)
    )
    up_share_map = {row.rarity_name: row.up_share for row in up_rate_result.scalars().all()}
    up_items_result = await session.execute(
        select(GachaBannerRunRateItem.rarity_name, GachaBannerRunRateItem.item_id)
        .where(GachaBannerRunRateItem.run_id == run.id)
    )
    up_item_map: dict[str, set[int]] = {}
    for rarity_name, item_id in up_items_result.all():
        up_item_map.setdefault(rarity_name, set()).add(item_id)

    user = await get_or_create_user(session, user_id)
    wallet_res = await session.execute(select(UserWallet).where(UserWallet.user_id == user.id))
    wallet = wallet_res.scalar_one_or_none()
    if wallet is None:
        wallet = UserWallet(user_id=user.id, deposit=0, score=0)
        session.add(wallet)
        await session.flush()

    draw_score_cost = await get_draw_score_cost(session)
    total_score_cost = draw_score_cost * draw_count
    if wallet.score < total_score_cost:
        raise ValueError(
            f"积分不足：本次需要 {total_score_cost} 积分（{draw_count} 抽 x {draw_score_cost}），当前积分 {wallet.score}"
        )
    wallet.score -= total_score_cost

    drawn_items: list[GachaItem] = []
    for _ in range(draw_count):
        rarity = _pick_rarity(rarities)
        drawn_items.append(
            _pick_item_with_up(
                rarity_items=items_by_rarity.get(rarity.name, []),
                up_share=up_share_map.get(rarity.name),
                up_item_ids=up_item_map.get(rarity.name, set()),
            )
        )

    for idx, drawn_item in enumerate(drawn_items, start=1):
        session.add(
            GachaDropRecord(
                user_id=user.id,
                draw_date=now,
                banner_pool_id=pool.id,
                template_id=template.id,
                item_id=drawn_item.id,
                scene_type=scene_type,
                scene_id=scene_id,
                draw_index=0 if draw_count == 1 else idx,
                score_cost=draw_score_cost,
            )
        )
    await session.commit()

    return [
        DrawResult(
            item_name=drawn_item.name,
            rarity_name=drawn_item.rarity_name,
            item_description=drawn_item.description,
            template_name=template.name,
            pool_name=pool.name,
        )
        for drawn_item in drawn_items
    ]


async def list_running_banners_in_group(
        session: async_scoped_session,
        scene_id: str,
        now: datetime,
) -> tuple[str, list[str]]:
    now = ensure_utc(now)
    group = await get_or_create_scene(session, scene_id)
    if group.default_template_name is None:
        raise ValueError(f"未设置默认模板，请联系管理员使用 设置默认模板#<模板名> 指令设置启用的模板")

    template_name = group.default_template_name
    stmt = (
        select(GachaBannerRun, GachaBannerPool, GachaTemplate)
        .join(GachaBannerPool, GachaBannerPool.id == GachaBannerRun.banner_pool_id)
        .join(GachaTemplate, GachaTemplate.id == GachaBannerPool.template_id)
        .where(GachaTemplate.name == template_name)
        .where(GachaBannerRun.start_at <= now)
        .where(or_(GachaBannerRun.end_at.is_(None), GachaBannerRun.end_at > now))
        .order_by(GachaBannerRun.start_at.desc(), GachaBannerRun.id.desc())
    )

    rows = (await session.execute(stmt)).all()
    if not rows:
        raise ValueError(f"模板「{template_name}」当前没有开放中的卡池")

    user_tz = await get_timezone(session)
    lines: list[str] = []
    for run, pool, template in rows:
        display_tz = ensure_utc(run.start_at).astimezone(user_tz)
        end_text = "永久开放"
        if run.end_at is not None:
            local_end = ensure_utc(run.end_at).astimezone(user_tz)
            end_text = local_end.strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"模板：{template.name} | 卡池：{pool.name} | "
            f"{display_tz.strftime('%Y-%m-%d %H:%M')} ~ {end_text}"
        )

    return template_name, lines


async def _resolve_rate_up_cfg_item_ids(
        session: async_scoped_session,
        template_id: int,
        template_name: str,
        rate_up_cfg: RateUpCfgByName | None,
) -> RateUpCfgById | None:
    if rate_up_cfg is None:
        return None

    rarity_result = await session.execute(
        select(GachaRarity).where(GachaRarity.template_id == template_id)
    )
    rarity_names = {r.name for r in rarity_result.scalars().all()}

    invalid_rarity = [name for name in rate_up_cfg if name not in rarity_names]
    if invalid_rarity:
        raise ValueError(f"模板「{template_name}」不存在这些稀有度：{', '.join(invalid_rarity)}")

    item_names = [
        item_name
        for _, rarity_cfg_item_names in rate_up_cfg.values()
        for item_name in rarity_cfg_item_names
    ]
    if len(item_names) != len(set(item_names)):
        raise ValueError("UP 配置中的卡片名不可重复")

    items_result = await session.execute(
        select(GachaItem).where(
            GachaItem.template_id == template_id,
            GachaItem.name.in_(item_names),
        )
    )
    item_map = {item.name: item for item in items_result.scalars().all()}

    missing_names = [item_name for item_name in item_names if item_name not in item_map]
    if missing_names:
        missing = ", ".join(sorted(set(missing_names)))
        raise ValueError(f"以下卡片不存在或不属于模板「{template_name}」：{missing}")

    resolved_cfg: RateUpCfgById = {}
    for rarity_name, (up_share, rarity_item_names) in rate_up_cfg.items():
        resolved_item_ids: list[int] = []
        for item_name in rarity_item_names:
            item = item_map[item_name]
            if item.rarity_name != rarity_name:
                raise ValueError(
                    f"卡片「{item_name}」稀有度为 {item.rarity_name}，"
                    f"不能配置到 {rarity_name}"
                )
            resolved_item_ids.append(item.id)
        resolved_cfg[rarity_name] = (up_share, resolved_item_ids)

    return resolved_cfg


async def _validate_drawability_preconditions(
        session: async_scoped_session,
        template_id: int,
        template_name: str,
        rate_up_cfg: RateUpCfgById | None,
) -> None:
    rarity_result = await session.execute(
        select(GachaRarity).where(GachaRarity.template_id == template_id)
    )
    rarities = rarity_result.scalars().all()
    if not rarities:
        raise ValueError(f"模板「{template_name}」未配置稀有度，无法创建卡池运行")

    weights = [rarity.weight for rarity in rarities]
    if any(weight < 0 for weight in weights):
        raise ValueError(f"模板「{template_name}」存在负数稀有度权重")
    if sum(weights) != 100:
        raise ValueError(f"模板「{template_name}」稀有度权重和必须为 100")

    item_result = await session.execute(
        select(GachaItem.id, GachaItem.rarity_name).where(GachaItem.template_id == template_id)
    )
    rarity_to_item_ids: dict[str, set[int]] = {rarity.name: set() for rarity in rarities}
    for item_id, rarity_name in item_result.all():
        rarity_to_item_ids.setdefault(rarity_name, set()).add(item_id)

    for rarity in rarities:
        if not rarity_to_item_ids.get(rarity.name):
            raise ValueError(
                f"模板「{template_name}」的稀有度「{rarity.name}」无可抽卡片，"
                "请先补充卡片"
            )

    if rate_up_cfg is None:
        return

    for rarity_name, (up_share, up_item_ids) in rate_up_cfg.items():
        all_item_ids = rarity_to_item_ids.get(rarity_name, set())
        non_up_count = len(all_item_ids - set(up_item_ids))
        if up_share < 100 and non_up_count == 0:
            raise ValueError(
                f"稀有度「{rarity_name}」UP 占比为 {up_share}%，"
                "但无常驻候选卡片"
            )


def _persist_rate_up_cfg(
        session: async_scoped_session,
        run_id: int,
        rate_up_cfg: RateUpCfgById | None,
):
    if rate_up_cfg is None:
        return

    for rarity_name, (up_share, rarity_item_ids) in rate_up_cfg.items():
        session.add(
            GachaBannerRunRate(
                run_id=run_id,
                rarity_name=rarity_name,
                up_share=up_share,
            )
        )
        for item_id in rarity_item_ids:
            session.add(
                GachaBannerRunRateItem(
                    run_id=run_id,
                    rarity_name=rarity_name,
                    item_id=item_id,
                )
            )


async def _format_create_banner_success_message(
        session: async_scoped_session,
        banner_name: str,
        template_name: str,
        run_id: int,
        start_at: datetime,
        end_at: datetime | None,
        action_text: str,
) -> str:
    display_tz = await get_timezone(session)
    local_start = ensure_utc(start_at).astimezone(display_tz)
    local_end = None if end_at is None else ensure_utc(end_at).astimezone(display_tz)

    return (
        f"卡池「{banner_name}」{action_text}（run_id={run_id}）\n"
        f"模板：{template_name}\n"
        f"时区：{display_tz.tzname(None)}\n"
        f"开启：{local_start.strftime('%Y-%m-%d %H:%M')}\n"
        f"结束：{"永久开放" if local_end is None else local_end.strftime("%Y-%m-%d %H:%M")}"
    )


def _intervals_overlap(
        left_start: datetime,
        left_end: datetime | None,
        right_start: datetime,
        right_end: datetime | None,
) -> bool:
    left_start = ensure_utc(left_start)
    right_start = ensure_utc(right_start)
    left_end = None if left_end is None else ensure_utc(left_end)
    right_end = None if right_end is None else ensure_utc(right_end)

    left_hits_right = True if right_end is None else left_start < right_end
    right_hits_left = True if left_end is None else right_start < left_end
    return left_hits_right and right_hits_left


async def _assert_no_overlapping_run(
        session: async_scoped_session,
        pool_id: int,
        start_at: datetime,
        end_at: datetime | None,
):
    user_tz = await get_timezone(session)

    result = await session.execute(
        select(GachaBannerRun)
        .where(GachaBannerRun.banner_pool_id == pool_id)
        .order_by(GachaBannerRun.start_at.desc(), GachaBannerRun.id.desc())
    )
    runs = result.scalars().all()

    for run in runs:
        run_start = ensure_utc(run.start_at)
        run_end = None if run.end_at is None else ensure_utc(run.end_at)
        if _intervals_overlap(start_at, end_at, run_start, run_end):
            local_start = run_start.astimezone(user_tz)

            if run_end is None:
                end_text = "永久开放"
            else:
                end_text = run_end.astimezone(user_tz).strftime("%Y-%m-%d %H:%M")

            interval_text = (
                f"{local_start.strftime('%Y-%m-%d %H:%M')} ~ {end_text}"
            )

            raise ValueError(
                f"时间区间与已存在运行记录冲突（run_id={run.id}，"
                f"{interval_text}）"
            )


async def _resolve_running_run(
        session: async_scoped_session,
        template_name: str,
        banner_name: str,
        now: datetime,
) -> tuple[GachaTemplate, GachaBannerPool, GachaBannerRun]:
    now = ensure_utc(now)
    stmt = (
        select(GachaTemplate, GachaBannerPool, GachaBannerRun)
        .join(GachaBannerPool, GachaBannerPool.template_id == GachaTemplate.id)
        .join(GachaBannerRun, GachaBannerRun.banner_pool_id == GachaBannerPool.id)
        .where(GachaTemplate.name == template_name)
        .where(GachaBannerPool.name == banner_name)
        .where(GachaBannerRun.start_at <= now)
        .where(or_(GachaBannerRun.end_at.is_(None), GachaBannerRun.end_at > now))
        .order_by(GachaBannerRun.start_at.desc(), GachaBannerRun.id.desc())
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        raise ValueError(f"模板「{template_name}」下未找到开放中的卡池「{banner_name}」")
    if len(rows) > 1:
        run_ids = ", ".join(str(row[2].id) for row in rows)
        raise ValueError(f"卡池「{banner_name}」存在多个开放运行记录（run_id={run_ids}），请联系管理员修复")

    template, pool, run = rows[0]
    return template, pool, run


def _pick_rarity(rarities: list[GachaRarity]) -> GachaRarity:
    positive = [rarity for rarity in rarities if rarity.weight > 0]
    if not positive:
        raise ValueError("模板稀有度权重异常：无可用权重")
    total = sum(rarity.weight for rarity in positive)
    if total != 100:
        raise ValueError(f"模板稀有度权重异常：总和应为 100，当前为 {total}")
    return random.choices(positive, weights=[rarity.weight for rarity in positive], k=1)[0]


def _pick_item_with_up(
        rarity_items: list[GachaItem],
        up_share: int | None,
        up_item_ids: set[int],
) -> GachaItem:
    if not rarity_items:
        raise ValueError("目标稀有度没有可抽卡片")

    if up_share is None:
        return random.choice(rarity_items)

    if not 1 <= up_share <= 100:
        raise ValueError(f"UP 配置异常：up_share={up_share}")

    up_items = [item for item in rarity_items if item.id in up_item_ids]
    non_up_items = [item for item in rarity_items if item.id not in up_item_ids]

    if up_share == 100:
        if not up_items:
            raise ValueError("UP 配置异常：up_share=100 但未配置有效 UP 卡片")
        return random.choice(up_items)

    pick_up = random.randint(1, 100) <= up_share
    if pick_up:
        if not up_items:
            raise ValueError("UP 配置异常：未找到有效 UP 卡片")
        return random.choice(up_items)

    if not non_up_items:
        raise ValueError("UP 配置异常：未找到常驻候选卡片")
    return random.choice(non_up_items)
