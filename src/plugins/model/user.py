from nonebot_plugin_orm import Model
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column


class User(Model):
    """平台用户主表"""
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    qq: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
