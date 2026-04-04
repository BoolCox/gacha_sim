from nonebot_plugin_orm import Model
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column


class Scene(Model):
    """场景表"""
    __tablename__ = "scene"

    id: Mapped[int] = mapped_column(primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    default_template_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
