from arclet.alconna import Arg, Args, Alconna, CommandMeta
from nonebot_plugin_alconna import on_alconna, Match
from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import select

from ..dependency.permission import ADMIN_PERMISSION
from ..model.gacha_item import GachaItem
from ..model.gacha_template import GachaTemplate, GachaRarity

add_item = on_alconna(
    Alconna(
        "添加卡片",
        Args(
            Arg("template_name", str),
            Arg("item_name", str),
            Arg("rarity_name", str),
            Arg("description", str),
            separators="#"
        ),
        meta=CommandMeta(compact=True),
        separators="#"
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
delete_item = on_alconna(
    Alconna(
        "删除卡片",
        Args(
            Arg("template_name", str),
            Arg("item_name", str),
            separators="#"
        ),
        meta=CommandMeta(compact=True),
        separators="#"
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)
list_items = on_alconna(
    Alconna(
        "列出卡片",
        Args["template_name", str],
        separators="#"
    ),
    skip_for_unmatch=False,
    permission=ADMIN_PERMISSION,
)


@add_item.handle()
async def add_item_handle(
        session: async_scoped_session,
        template_name: Match[str],
        item_name: Match[str],
        rarity_name: Match[str],
        description: Match[str],
):
    result = await session.execute(
        select(GachaTemplate).where(GachaTemplate.name == template_name.result)
    )
    template = result.scalar_one_or_none()
    if template is None:
        await add_item.finish(f"模板「{template_name.result}」不存在")

    rarity_result = await session.execute(
        select(GachaRarity).where(
            GachaRarity.template_id == template.id,
            GachaRarity.name == rarity_name.result,
        )
    )
    if rarity_result.scalar_one_or_none() is None:
        await add_item.finish(f"稀有度「{rarity_name.result}」在模板「{template_name.result}」中不存在")

    existing = await session.execute(
        select(GachaItem).where(
            GachaItem.template_id == template.id,
            GachaItem.name == item_name.result,
        )
    )
    if existing.scalar_one_or_none() is not None:
        await add_item.finish(f"卡片「{item_name.result}」在模板「{template_name.result}」中已存在")

    desc = description.result or None
    session.add(GachaItem(
        template_id=template.id,
        name=item_name.result,
        rarity_name=rarity_name.result,
        description=desc,
    ))
    await session.commit()
    await add_item.finish(f"卡片「{item_name.result}」已添加至模板「{template_name.result}」（{rarity_name.result}）")


@delete_item.handle()
async def delete_item_handle(
        session: async_scoped_session,
        template_name: Match[str],
        item_name: Match[str],
):
    result = await session.execute(
        select(GachaTemplate).where(GachaTemplate.name == template_name.result)
    )
    template = result.scalar_one_or_none()
    if template is None:
        await delete_item.finish(f"模板「{template_name.result}」不存在")

    item_result = await session.execute(
        select(GachaItem).where(
            GachaItem.template_id == template.id,
            GachaItem.name == item_name.result,
        )
    )
    item = item_result.scalar_one_or_none()
    if item is None:
        await delete_item.finish(f"卡片「{item_name.result}」在模板「{template_name.result}」中不存在")

    await session.delete(item)
    await session.commit()
    await delete_item.finish(f"卡片「{item_name.result}」已从模板「{template_name.result}」删除")


@list_items.handle()
async def list_items_handle(
        session: async_scoped_session,
        template_name: Match[str],
):
    result = await session.execute(
        select(GachaTemplate).where(GachaTemplate.name == template_name.result)
    )
    template = result.scalar_one_or_none()
    if template is None:
        await list_items.finish(f"模板「{template_name.result}」不存在")

    items_result = await session.execute(
        select(GachaItem).where(GachaItem.template_id == template.id)
    )
    items = items_result.scalars().all()
    if not items:
        await list_items.finish(f"模板「{template_name.result}」暂无卡片")

    lines = "\n".join(
        f"  [{i.id}] {i.name}（{i.rarity_name}）{f'：{i.description}' if i.description else ''}" for i in items)
    await list_items.finish(f"模板「{template_name.result}」卡片列表：\n{lines}")
