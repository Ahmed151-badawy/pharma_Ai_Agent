from datetime import date, timedelta


def test_expired_batch_stock_out_is_strictly_rejected(client, pharmacist_headers):
    """Verify that stock_out (sales/dispensing) from an expired batch is blocked."""
    # IBU-1001 is an expired batch in demo seed data
    resp = client.post("/api/v1/inventory/movements", headers=pharmacist_headers,
                       json={"batch_id": "IBU-1001", "movement_type": "stock_out", "quantity": 1})
    assert resp.status_code == 409
    assert "Cannot dispense or sell expired batch" in resp.json()["detail"]


def test_expired_batch_disposal_is_permitted(client, pharmacist_headers):
    """Verify that disposal of an expired batch is permitted."""
    resp = client.post("/api/v1/inventory/movements", headers=pharmacist_headers,
                       json={"batch_id": "IBU-1001", "movement_type": "disposal", "quantity": 5, "note": "Spoiled / expired"})
    assert resp.status_code == 201
    data = resp.json()
    assert "Dispose 5 units from batch IBU-1001" in data["summary"]

    # Confirm movement
    token = data["confirmation_token"]
    confirm_resp = client.post(f"/api/v1/inventory/movements/{token}/confirm", headers=pharmacist_headers)
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["change"] == -5


def test_fefo_violation_and_override(client, pharmacist_headers, db):
    """Verify that FEFO policy prevents dispensing later batch when earlier batch is available, unless overridden."""
    today = date.today()
    # Add a second Amoxicillin batch expiring further in the future
    # Medicine 1 has AMX-2026 expiring in ~90 days
    with db.begin() as conn:
        from sqlalchemy import text
        conn.execute(
            text("INSERT INTO batches (batch_id, medicine_id, supplier_name, quantity_in_stock, expiration_date, status) "
                 "VALUES ('AMX-FUTURE', 1, 'PharmaCorp', 50, :exp, 'Active')"),
            {"exp": today + timedelta(days=365)}
        )

    # Attempting to dispense from AMX-FUTURE without force_fefo should fail with FEFO violation
    resp = client.post("/api/v1/inventory/movements", headers=pharmacist_headers,
                       json={"batch_id": "AMX-FUTURE", "movement_type": "stock_out", "quantity": 5})
    assert resp.status_code == 409
    assert "FEFO Violation" in resp.json()["detail"]
    assert "AMX-2026" in resp.json()["detail"]

    # Attempting with force_fefo=True should succeed
    override_resp = client.post("/api/v1/inventory/movements", headers=pharmacist_headers,
                                json={"batch_id": "AMX-FUTURE", "movement_type": "stock_out", "quantity": 5, "force_fefo": True})
    assert override_resp.status_code == 201


def test_fefo_recommendation_endpoint(client, viewer_headers, db):
    """Verify that /fefo/recommend calculates correct batch order."""
    today = date.today()
    # Insert multiple batches for Medicine 1 with different expiry dates and quantities
    with db.begin() as conn:
        from sqlalchemy import text
        conn.execute(
            text("INSERT INTO batches (batch_id, medicine_id, supplier_name, quantity_in_stock, expiration_date, status) "
                 "VALUES ('AMX-FAR', 1, 'SupplierA', 100, :exp, 'Active')"),
            {"exp": today + timedelta(days=200)}
        )

    # Medicine 1 has AMX-2026 (qty: 15, exp: +90d) and AMX-FAR (qty: 100, exp: +200d)
    resp = client.get("/api/v1/inventory/fefo/recommend?medicine_id=1&quantity=20", headers=viewer_headers)
    assert resp.status_code == 200
    rec = resp.json()
    assert rec["medicine_id"] == 1
    assert rec["requested_quantity"] == 20
    assert rec["allocated_quantity"] == 20
    assert rec["sufficient_stock"] is True
    # First batch must be AMX-2026 (15 units)
    assert rec["batches"][0]["batch_id"] == "AMX-2026"
    assert rec["batches"][0]["quantity_to_dispense"] == 15
    # Second batch must be AMX-FAR (5 units)
    assert rec["batches"][1]["batch_id"] == "AMX-FAR"
    assert rec["batches"][1]["quantity_to_dispense"] == 5
