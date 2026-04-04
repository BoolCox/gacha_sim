from nonebot_plugin_orm import Model
from sqlalchemy import ForeignKeyConstraint, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class GachaItem(Model):
    """卡片：归属于某个抽卡模板，rarity 由数据库外键约束至 GachaRarity"""
    __tablename__ = "gacha_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(Text)
    rarity_name: Mapped[str] = mapped_column(Text, comment="卡片稀有度，FK 至 gacha_rarity(template_id, name)")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("template_id", "name"),
        ForeignKeyConstraint(
            ["template_id", "rarity_name"],
            ["gacha_rarity.template_id", "gacha_rarity.name"],
        ),
    )
