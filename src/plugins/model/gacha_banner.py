from datetime import datetime

from nonebot_plugin_orm import Model
from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    TIMESTAMP,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class GachaBannerPool(Model):
    """卡池定义：静态信息，每次运行见关联的 GachaBannerRun"""
    __tablename__ = "gacha_banner_pool"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("gacha_template.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("template_id", "name"),
    )


class GachaBannerRun(Model):
    """卡池运行记录：每次开放对应一行，创建时确定 start_at/end_at（end_at 可为空表示永久开放）"""
    __tablename__ = "gacha_banner_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    banner_pool_id: Mapped[int] = mapped_column(ForeignKey("gacha_banner_pool.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, comment="为空表示永久开放")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class GachaBannerRunRate(Model):
    """运行记录中的稀有度 UP 概率配置（每个稀有度一行）"""
    __tablename__ = "gacha_banner_run_rate"

    run_id: Mapped[int] = mapped_column(ForeignKey("gacha_banner_run.id"), primary_key=True)
    # 这里难以在数据库层面确保 rarity_name 一定在所属 template 存在所以需要走业务层校验
    rarity_name: Mapped[str] = mapped_column(Text, primary_key=True)
    up_share: Mapped[int] = mapped_column(Integer, comment="该稀有度中分配给 UP 卡的百分比（1-100）")


class GachaBannerRunRateItem(Model):
    """运行记录中的 UP 卡配置（某个稀有度下有哪些卡）"""
    __tablename__ = "gacha_banner_run_rate_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    rarity_name: Mapped[str] = mapped_column(Text)
    item_id: Mapped[int] = mapped_column(ForeignKey("gacha_item.id"), index=True)

    __table_args__ = (
        UniqueConstraint("run_id", "item_id"),
        ForeignKeyConstraint(
            ["run_id", "rarity_name"],
            ["gacha_banner_run_rate.run_id", "gacha_banner_run_rate.rarity_name"],
        ),
    )
