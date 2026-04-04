from datetime import datetime

from nonebot_plugin_orm import Model
from sqlalchemy import ForeignKey, Integer, TIMESTAMP, Enum
from sqlalchemy.orm import Mapped, mapped_column

from ..dependency.enum_typy import SceneType


class GachaDropRecord(Model):
    """抽卡掉落记录（每个掉落一行）"""
    __tablename__ = "gacha_drop_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    draw_date: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), index=True)
    banner_pool_id: Mapped[int] = mapped_column(ForeignKey("gacha_banner_pool.id"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("gacha_template.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("gacha_item.id"), index=True)
    scene_type: Mapped[SceneType] = mapped_column(Enum(SceneType))
    scene_id: Mapped[str] = mapped_column(index=True)
    draw_index: Mapped[int] = mapped_column(Integer, default=0, comment="同一批次抽卡内的顺序")
    score_cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="本条掉落对应消耗积分")
