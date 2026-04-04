from nonebot_plugin_orm import Model
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column


class GachaTemplate(Model):
    """抽卡模板：供多个 GachaBannerPool 复用，稀有度定义见关联的 GachaRarity"""
    __tablename__ = "gacha_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class GachaRarity(Model):
    """稀有度定义：归属于某个抽卡模板，同模板下所有 weight 合计须为 100（应用层校验）"""
    __tablename__ = "gacha_rarity"

    template_id: Mapped[int] = mapped_column(ForeignKey("gacha_template.id"), primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, comment="稀有度权重，同模板下合计须为 100")
