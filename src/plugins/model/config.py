from nonebot_plugin_orm import Model
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column


class Config(Model):
    """系统配置表"""
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)

    value: Mapped[str] = mapped_column(String(200))
