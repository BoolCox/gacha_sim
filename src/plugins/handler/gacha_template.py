from arclet.alconna import Arg, Args, Alconna
from nonebot.internal.params import ArgPlainText
from nonebot_plugin_alconna import on_alconna, Match
from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from ..dependency.permission import ADMIN_PERMISSION
from ..model.gacha_template import GachaTemplate, GachaRarity

create_template = on_alconna(
    Alconna(
        "创建卡池模板",
        Args(
            Arg("name", str),
            Arg("description", str),
            separators="#"
        ),
        separators="#",
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
delete_template = on_alconna(
    Alconna(
        "删除卡池模板",
        Args["name", str],
        separators="#"
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
list_template = on_alconna(
    "列出卡池模板",
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION
)


@create_template.got("rarity", "请输入稀有度及概率定义（格式：稀有度#概率，每行一组）")
async def create_template_got(
        session: async_scoped_session,
        name: Match[str],
        description: Match[str],
        rarity: str = ArgPlainText()
):
    rarity = rarity.strip()
    if not rarity:
        await create_template.finish("未提供稀有度，已取消")

    # 解析 "稀有度#概率\n..." 格式
    rarity_entries: list[tuple[str, int]] = []
    for line in rarity.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("#", 1)
        if len(parts) != 2:
            await create_template.finish(f"格式错误：{line!r}，应为「稀有度#概率」")
        rarity_name, weight_str = parts[0].strip(), parts[1].strip()
        if not weight_str.isdigit():
            await create_template.finish(f"概率必须为整数：{weight_str!r}")
        rarity_entries.append((rarity_name, int(weight_str)))

    total = sum(w for _, w in rarity_entries)
    if total != 100:
        await create_template.finish(f"所有稀有度概率之和须为 100，当前为 {total}")

    try:
        template = GachaTemplate(name=name.result, description=description.result)
        session.add(template)
        await session.flush()

        for rarity_name, weight in rarity_entries:
            session.add(GachaRarity(template_id=template.id, name=rarity_name, weight=weight))

        await session.commit()

    except IntegrityError:
        await session.rollback()
        await create_template.finish(f"模板「{name.result}」已存在")

    lines = "\n".join(f"  {r}：{w}%" for r, w in rarity_entries)
    await create_template.finish(f"模板「{name.result}」创建成功\n{lines}")


@delete_template.handle()
async def delete_template_handle(
        session: async_scoped_session,
        name: Match[str]
):
    result = await session.execute(select(GachaTemplate).where(GachaTemplate.name == name.result))
    template = result.scalar_one_or_none()
    if template is None:
        await delete_template.finish(f"模板「{name.result}」不存在")

    await session.execute(delete(GachaRarity).where(GachaRarity.template_id == template.id))
    await session.delete(template)
    await session.commit()
    await delete_template.finish(f"模板「{name.result}」已删除")


@list_template.handle()
async def list_template_handle(session: async_scoped_session):
    result = await session.execute(select(GachaTemplate))
    templates = result.scalars().all()
    if not templates:
        await list_template.finish("暂无卡池模板")

    lines = "\n".join(f"  [{t.id}] {t.name}：{t.description or '无描述'}" for t in templates)
    await list_template.finish(f"卡池模板列表：\n{lines}")
