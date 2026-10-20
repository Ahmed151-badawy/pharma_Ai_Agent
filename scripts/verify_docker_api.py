import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8001"

print("--- 1. Probing /health on Docker port 8001 ---")
with urllib.request.urlopen(f"{BASE_URL}/health") as resp:
    data = json.loads(resp.read().decode())
    print("Health response:", data)
    assert data["status"] == "healthy"

print("\n--- 2. Authenticating as admin ---")
admin_user = os.environ.get("ADMIN_USERNAME", "admin")
admin_pwd = os.environ.get("ADMIN_PASSWORD")

login_payload = json.dumps({"username": admin_user, "password": admin_pwd}).encode()
login_req = urllib.request.Request(
    f"{BASE_URL}/api/v1/auth/login",
    data=login_payload,
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(login_req) as resp:
    login_data = json.loads(resp.read().decode())
    token = login_data["access_token"]
    print("Docker container admin login: SUCCESS")

auth_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

print("\n--- 3. Testing expired-batch stock_out (IBU-1001) ---")
stock_out_payload = json.dumps({"batch_id": "IBU-1001", "movement_type": "stock_out", "quantity": 1}).encode()
req = urllib.request.Request(f"{BASE_URL}/api/v1/inventory/movements", data=stock_out_payload, headers=auth_headers)
try:
    urllib.request.urlopen(req)
    print("CRITICAL FAILURE: Expired batch stock_out was allowed!", file=sys.stderr)
    sys.exit(1)
except urllib.error.HTTPError as e:
    err_body = json.loads(e.read().decode())
    detail = err_body.get("detail", "")
    print(f"Docker API expired stock_out rejected as expected: HTTP {e.code}")
    print(f"Detail message: {detail}")
    assert e.code == 409
    assert "Cannot dispense or sell expired batch" in detail

print("\n--- 4. Testing disposal movement on expired batch (IBU-1001) ---")
disp_payload = json.dumps({
    "batch_id": "IBU-1001",
    "movement_type": "disposal",
    "quantity": 2,
    "note": "Regulatory disposal"
}).encode()
req = urllib.request.Request(f"{BASE_URL}/api/v1/inventory/movements", data=disp_payload, headers=auth_headers)
with urllib.request.urlopen(req) as resp:
    assert resp.status == 201
    disp_data = json.loads(resp.read().decode())
    print("Disposal requested successfully: HTTP 201")
    print("Summary:", disp_data["summary"])
    conf_token = disp_data["confirmation_token"]

confirm_req = urllib.request.Request(
    f"{BASE_URL}/api/v1/inventory/movements/{conf_token}/confirm",
    data=b"",
    headers=auth_headers
)
with urllib.request.urlopen(confirm_req) as resp:
    assert resp.status == 200
    conf_data = json.loads(resp.read().decode())
    print("Disposal confirmed successfully: HTTP 200")
    print("Stock delta recorded:", conf_data["change"])
    assert conf_data["change"] == -2

print("\n--- 5. Testing FEFO recommendation endpoint ---")
req = urllib.request.Request(f"{BASE_URL}/api/v1/inventory/fefo/recommend?medicine_id=1&quantity=10", headers=auth_headers)
with urllib.request.urlopen(req) as resp:
    assert resp.status == 200
    fefo_data = json.loads(resp.read().decode())
    print("FEFO recommendation returned: HTTP 200")
    print("Medicine ID:", fefo_data["medicine_id"])
    print("Allocated quantity:", fefo_data["allocated_quantity"])
    print("Batches allocated:", len(fefo_data["batches"]))
    assert fefo_data["allocated_quantity"] == 10
    assert len(fefo_data["batches"]) >= 1

print("\nAll Docker runtime API verification probes PASSED successfully!")
