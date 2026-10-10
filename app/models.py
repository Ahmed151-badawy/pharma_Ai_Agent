from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Medicine(Base):
    __tablename__ = "medicines"

    medicine_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generic_name: Mapped[str] = mapped_column(String(100))
    brand_name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(50))
    minimum_stock_level: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    storage_requirements: Mapped[str | None] = mapped_column(String(255))

    batches: Mapped[list["Batch"]] = relationship(back_populates="medicine")


class Batch(Base):
    __tablename__ = "batches"

    batch_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.medicine_id"))
    supplier_name: Mapped[str | None] = mapped_column(String(100))
    quantity_in_stock: Mapped[int] = mapped_column(Integer)
    production_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="Active", server_default="Active")

    medicine: Mapped[Medicine] = relationship(back_populates="batches")


class InventoryLog(Base):
    __tablename__ = "inventory_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.batch_id"))
    transaction_type: Mapped[str] = mapped_column(String(20))
    quantity_changed: Mapped[int] = mapped_column(Integer)
    transaction_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    handled_by: Mapped[str | None] = mapped_column(String(50))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(20))  # viewer | pharmacist | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_ts", "ts"), Index("ix_audit_logs_action", "action"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(45))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    pages: Mapped[int] = mapped_column(Integer)
    chunks: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAction(Base):
    """A stock movement that has been requested but not yet confirmed (two-step write)."""

    __tablename__ = "pending_actions"

    token: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
