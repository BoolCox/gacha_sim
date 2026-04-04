from datetime import datetime

from nonebot_plugin_orm import Model
from sqlalchemy import ForeignKey, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column


class Checkin(Model):
    __tablename__ = "checkin"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    checkin_date: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), index=True)
