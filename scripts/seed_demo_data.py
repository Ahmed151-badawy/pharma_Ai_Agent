"""Idempotent demo data. Dates are relative to today, so the alerts always have something to show."""
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Batch, Medicine

MEDICINES = [
    (1, "Amoxicillin", "Amoxil", "Antibiotic", 50, "Store below 25°C (77°F). Protect from moisture and light."),
    (2, "Ibuprofen", "Advil", "Analgesic", 100, "Store at 20°C to 25°C (68°F to 77°F). Avoid heat above 40°C."),
    (3, "Metformin", "Glucophage", "Antidiabetic", 40, "Store at 20°C to 25°C (68°F to 77°F). Protect from light and moisture."),
]


def seed(session: Session) -> None:
    today = date.today()
    for mid, generic, brand, category, minimum, storage in MEDICINES:
        session.merge(Medicine(medicine_id=mid, generic_name=generic, brand_name=brand, category=category,
                               minimum_stock_level=minimum, storage_requirements=storage))
    session.flush()

    batches = [  # batch_id, medicine_id, supplier, qty, produced, expires
        ("AMX-2026", 1, "PharmaCorp", 15, today - timedelta(days=280), today + timedelta(days=90)),
        ("IBU-9942", 2, "HealthDistributors", 120, today - timedelta(days=150), today + timedelta(days=400)),
        ("MET-5510", 3, "GlobalMeds", 25, today - timedelta(days=700), today + timedelta(days=25)),
        ("IBU-1001", 2, "HealthDistributors", 30, today - timedelta(days=800), today - timedelta(days=10)),
    ]
    for batch_id, mid, supplier, qty, produced, expires in batches:
        if session.get(Batch, batch_id) is None:  # never overwrite real stock levels
            session.add(Batch(batch_id=batch_id, medicine_id=mid, supplier_name=supplier, quantity_in_stock=qty,
                              production_date=produced, expiration_date=expires, status="Active"))
    session.commit()

    if session.get_bind().dialect.name == "postgresql":  # explicit ids above do not advance the SERIAL counter
        session.execute(text(
            "SELECT setval(pg_get_serial_sequence('medicines', 'medicine_id'), (SELECT MAX(medicine_id) FROM medicines))"
        ))
        session.commit()


def main() -> None:
    with SessionLocal() as session:
        seed(session)
    print("✓ Demo data ready (3 medicines, 4 batches).")


if __name__ == "__main__":
    main()
