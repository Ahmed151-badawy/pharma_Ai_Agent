"""Inventory business logic: alerts, daily report and two-step (confirmed) stock movements."""
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Batch, InventoryLog, Medicine, PendingAction, User


class InventoryError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _batch_row(batch: Batch, medicine: Medicine, today: date) -> dict:
    return {
        "batch_id": batch.batch_id,
        "medicine": medicine.generic_name,
        "quantity": batch.quantity_in_stock,
        "expiration_date": batch.expiration_date.isoformat(),
        "days_left": (batch.expiration_date - today).days,
    }


def list_batches(session: Session) -> list[dict]:
    today = date.today()
    rows = session.execute(
        select(Batch, Medicine).join(Medicine).order_by(Batch.expiration_date)
    ).all()
    return [_batch_row(b, m, today) | {"status": b.status, "supplier": b.supplier_name} for b, m in rows]


def get_alerts(session: Session, days: int = 60, today: date | None = None) -> dict:
    """Expired batches, batches expiring within `days`, and medicines below their minimum stock level."""
    today = today or date.today()
    horizon = today + timedelta(days=days)

    rows = session.execute(
        select(Batch, Medicine).join(Medicine).where(Batch.quantity_in_stock > 0).order_by(Batch.expiration_date)
    ).all()
    expired = [_batch_row(b, m, today) for b, m in rows if b.expiration_date < today]
    expiring = [_batch_row(b, m, today) for b, m in rows if today <= b.expiration_date <= horizon]

    usable = func.coalesce(
        func.sum(case((Batch.expiration_date >= today, Batch.quantity_in_stock), else_=0)), 0
    )
    stock_rows = session.execute(
        select(Medicine.generic_name, Medicine.minimum_stock_level, usable)
        .outerjoin(Batch, Batch.medicine_id == Medicine.medicine_id)
        .group_by(Medicine.medicine_id)
        .order_by(Medicine.generic_name)
    ).all()
    low_stock = [
        {"medicine": name, "usable_stock": int(stock), "minimum_stock_level": minimum}
        for name, minimum, stock in stock_rows
        if stock < minimum
    ]
    return {"as_of": today.isoformat(), "days_ahead": days, "expired": expired, "expiring_soon": expiring, "low_stock": low_stock}


def daily_report(session: Session, today: date | None = None) -> dict:
    today = today or date.today()
    start = datetime.combine(today, time.min)
    movements = session.execute(
        select(InventoryLog.transaction_type, func.count(), func.coalesce(func.sum(InventoryLog.quantity_changed), 0))
        .where(InventoryLog.transaction_date >= start)
        .group_by(InventoryLog.transaction_type)
    ).all()
    alerts = get_alerts(session, today=today)
    return {
        "date": today.isoformat(),
        "totals": {
            "medicines": session.scalar(select(func.count()).select_from(Medicine)),
            "batches": session.scalar(select(func.count()).select_from(Batch)),
            "units_in_stock": int(session.scalar(select(func.coalesce(func.sum(Batch.quantity_in_stock), 0)))),
        },
        "movements_today": [
            {"type": t, "transactions": int(n), "net_units": int(units)} for t, n, units in movements
        ],
        "alert_counts": {
            "expired": len(alerts["expired"]),
            "expiring_soon": len(alerts["expiring_soon"]),
            "low_stock": len(alerts["low_stock"]),
        },
        "alerts": alerts,
    }


def get_fefo_recommendation(session: Session, medicine_id: int, quantity: int) -> dict:
    """Calculate FEFO batch allocations for a given medicine and required quantity."""
    medicine = session.get(Medicine, medicine_id)
    if medicine is None:
        raise InventoryError(f"Medicine id {medicine_id} not found.", 404)
    today = date.today()
    usable_batches = session.scalars(
        select(Batch)
        .where(
            Batch.medicine_id == medicine_id,
            Batch.quantity_in_stock > 0,
            Batch.expiration_date >= today,
        )
        .order_by(Batch.expiration_date.asc())
    ).all()

    allocations = []
    needed = quantity
    allocated_total = 0

    for b in usable_batches:
        if needed <= 0:
            break
        take = min(b.quantity_in_stock, needed)
        allocations.append({
            "batch_id": b.batch_id,
            "expiration_date": b.expiration_date.isoformat(),
            "available_stock": b.quantity_in_stock,
            "quantity_to_dispense": take,
        })
        needed -= take
        allocated_total += take

    return {
        "medicine_id": medicine_id,
        "requested_quantity": quantity,
        "allocated_quantity": allocated_total,
        "sufficient_stock": allocated_total >= quantity,
        "batches": allocations,
    }


def request_movement(session: Session, user: User, batch_id: str, movement_type: str, quantity: int,
                     note: str | None = None, force_fefo: bool = False) -> PendingAction:
    """Step 1: validate and store a pending movement. Nothing changes in stock yet."""
    batch = session.get(Batch, batch_id)
    if batch is None:
        raise InventoryError(f"Batch '{batch_id}' not found.", 404)

    today = date.today()

    if movement_type == "stock_out":
        if batch.expiration_date < today:
            raise InventoryError(
                f"Cannot dispense or sell expired batch '{batch_id}' (expired on {batch.expiration_date.isoformat()}). "
                "Use movement_type='disposal' to remove expired stock.",
                409,
            )
        if quantity > batch.quantity_in_stock:
            raise InventoryError(f"Cannot remove {quantity} units: only {batch.quantity_in_stock} in stock.", 409)

        # FEFO policy: earlier-expiring usable batch of same medicine must be dispensed first
        if not force_fefo:
            earlier_batch = session.scalar(
                select(Batch)
                .where(
                    Batch.medicine_id == batch.medicine_id,
                    Batch.batch_id != batch.batch_id,
                    Batch.quantity_in_stock > 0,
                    Batch.expiration_date >= today,
                    Batch.expiration_date < batch.expiration_date,
                )
                .order_by(Batch.expiration_date.asc())
                .limit(1)
            )
            if earlier_batch:
                raise InventoryError(
                    f"FEFO Violation: Batch '{earlier_batch.batch_id}' (expires {earlier_batch.expiration_date.isoformat()}, "
                    f"{earlier_batch.quantity_in_stock} units available) must be dispensed before '{batch.batch_id}' "
                    f"(expires {batch.expiration_date.isoformat()}). Set force_fefo=True to override.",
                    409,
                )

    elif movement_type == "disposal":
        if quantity > batch.quantity_in_stock:
            raise InventoryError(f"Cannot dispose {quantity} units: only {batch.quantity_in_stock} in stock.", 409)

    elif movement_type == "stock_in":
        if batch.expiration_date < today:
            raise InventoryError("Cannot add stock to an expired batch.", 409)
    else:
        raise InventoryError(f"Unsupported movement type '{movement_type}'.", 400)

    if movement_type == "stock_in":
        verb, prep = "Add", "to"
    elif movement_type == "disposal":
        verb, prep = "Dispose", "from"
    else:
        verb, prep = "Remove", "from"

    summary = f"{verb} {quantity} units {prep} batch {batch_id} (currently {batch.quantity_in_stock})"
    pending = PendingAction(
        token=str(uuid.uuid4()),
        user_id=user.id,
        action_type=movement_type,
        payload={"batch_id": batch_id, "quantity": quantity, "note": note, "summary": summary,
                 "force_fefo": force_fefo},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=get_settings().confirmation_ttl_minutes),
    )
    session.add(pending)
    session.commit()
    return pending


def confirm_movement(session: Session, user: User, token: str) -> dict:
    """Step 2: apply a pending movement atomically and write the inventory log."""
    pending = session.scalar(select(PendingAction).where(PendingAction.token == token).with_for_update())
    if pending is None or pending.user_id != user.id:  # same answer for "not yours" and "unknown"
        raise InventoryError("Unknown confirmation token.", 404)
    if pending.consumed:
        raise InventoryError("This action was already confirmed.", 409)
    if pending.expires_at < datetime.now(timezone.utc):
        raise InventoryError("Confirmation token expired. Please request the movement again.", 410)

    batch = session.scalar(select(Batch).where(Batch.batch_id == pending.payload["batch_id"]).with_for_update())
    if batch is None:
        raise InventoryError("Batch no longer exists.", 404)

    # Re-validate expiration under lock for stock_out
    today = date.today()
    if pending.action_type == "stock_out" and batch.expiration_date < today:
        raise InventoryError(
            f"Batch '{batch.batch_id}' has expired since movement was requested (expired on {batch.expiration_date.isoformat()}). "
            "Cannot dispense expired stock.",
            409,
        )

    quantity = pending.payload["quantity"]
    delta = quantity if pending.action_type == "stock_in" else -quantity
    if batch.quantity_in_stock + delta < 0:
        raise InventoryError(f"Stock changed meanwhile: only {batch.quantity_in_stock} units left.", 409)

    batch.quantity_in_stock += delta
    session.add(InventoryLog(
        batch_id=batch.batch_id,
        transaction_type=pending.action_type.upper(),
        quantity_changed=delta,
        handled_by=user.username,
    ))
    pending.consumed = True
    session.commit()
    return {"batch_id": batch.batch_id, "new_quantity": batch.quantity_in_stock, "change": delta,
            "summary": pending.payload["summary"]}

