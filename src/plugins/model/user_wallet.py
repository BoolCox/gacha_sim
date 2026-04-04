from datetime import datetime

from nonebot_plugin_orm import Model
from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class UserWallet(Model):
    """用户资产账户：deposit 为存款本金，score 为可用积分。"""
    __tablename__ = "user_wallet"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    deposit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    interest_last_claim_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id"),
    )
