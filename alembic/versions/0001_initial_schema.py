"""Initial schema.

Every table is created only if it does not exist yet, so this migration can also ADOPT a database
that was previously created by the old database_setup.py script (medicines / batches / inventory_logs).

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    def missing(table: str) -> bool:
        return not inspector.has_table(table)

    if missing("medicines"):
        op.create_table(
            "medicines",
            sa.Column("medicine_id", sa.Integer, primary_key=True),
            sa.Column("generic_name", sa.String(100), nullable=False),
            sa.Column("brand_name", sa.String(100), nullable=False),
            sa.Column("category", sa.String(50)),
            sa.Column("minimum_stock_level", sa.Integer, server_default="50"),
            sa.Column("storage_requirements", sa.String(255)),
        )
    if missing("batches"):
        op.create_table(
            "batches",
            sa.Column("batch_id", sa.String(50), primary_key=True),
            sa.Column("medicine_id", sa.Integer, sa.ForeignKey("medicines.medicine_id"), nullable=False),
            sa.Column("supplier_name", sa.String(100)),
            sa.Column("quantity_in_stock", sa.Integer, nullable=False),
            sa.Column("production_date", sa.Date),
            sa.Column("expiration_date", sa.Date, nullable=False),
            sa.Column("status", sa.String(20), server_default="Active"),
            sa.CheckConstraint("quantity_in_stock >= 0", name="ck_batches_quantity_non_negative"),
        )
    if missing("inventory_logs"):
        op.create_table(
            "inventory_logs",
            sa.Column("log_id", sa.Integer, primary_key=True),
            sa.Column("batch_id", sa.String(50), sa.ForeignKey("batches.batch_id")),
            sa.Column("transaction_type", sa.String(20), nullable=False),
            sa.Column("quantity_changed", sa.Integer, nullable=False),
            sa.Column("transaction_date", sa.DateTime, server_default=sa.func.now()),
            sa.Column("handled_by", sa.String(50)),
        )
    if missing("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("username", sa.String(50), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(128), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if missing("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("user_id", sa.Integer),
            sa.Column("username", sa.String(50)),
            sa.Column("action", sa.String(50), nullable=False),
            sa.Column("detail", sa.JSON),
            sa.Column("request_id", sa.String(64)),
            sa.Column("ip", sa.String(45)),
        )
        op.create_index("ix_audit_logs_ts", "audit_logs", ["ts"])
        op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    if missing("documents"):
        op.create_table(
            "documents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False, unique=True),
            sa.Column("pages", sa.Integer, nullable=False),
            sa.Column("chunks", sa.Integer, nullable=False),
            sa.Column("uploaded_by", sa.String(50), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if missing("pending_actions"):
        op.create_table(
            "pending_actions",
            sa.Column("token", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.Integer, nullable=False),
            sa.Column("action_type", sa.String(30), nullable=False),
            sa.Column("payload", sa.JSON, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed", sa.Boolean, nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    # Only drop tables introduced by this application. The three core inventory tables are left in
    # place on purpose, because they may pre-date Alembic and contain real data.
    for table in ("pending_actions", "documents", "audit_logs", "users"):
        op.drop_table(table)
