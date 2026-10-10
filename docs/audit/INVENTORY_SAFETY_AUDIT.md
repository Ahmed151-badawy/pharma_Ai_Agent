# Inventory Safety & Clinical Decision Audit: Expired-Batch Dispensing & FEFO

> **Document:** `docs/audit/INVENTORY_SAFETY_AUDIT.md`  
> **Auditor:** Pharmaceutical System Safety & Clinical Engineering Review  
> **Date:** 2026-10-10  
> **Target Subsystems:** [`app/inventory.py`](file:///f:/pharma_agent/app/inventory.py), [`app/routers/inventory.py`](file:///f:/pharma_agent/app/routers/inventory.py), [`app/models.py`](file:///f:/pharma_agent/app/models.py), [`app/schemas.py`](file:///f:/pharma_agent/app/schemas.py)

---

## 1. Executive Summary

A targeted safety audit was conducted on the Pharma AI Agent's inventory movement and lifecycle management subsystems, focusing on:
1. **Expired-Batch Sales / Dispensing Prevention**
2. **FEFO (First Expired, First Out) Policy Enforcement**
3. **Quarantine / Disposal State Separation**

### Key Clinical & Safety Finding
The current implementation exhibits an asymmetric safety check:
* Adding stock (`stock_in`) to an expired batch is **blocked** (`Cannot add stock to an expired batch.`).
* **However, dispensing stock (`stock_out`) from an expired batch is completely UNRESTRICTED.** An expired batch can be confirmed and deducted for distribution without warning, representing a major patient safety violation and non-compliance with Good Distribution Practices (GDP) and FDA regulations (21 CFR § 211.137 / 211.150).

---

## 2. Empirical Evidence & Defect Breakdown

### Defect S-001: Missing Expiration Guard on Stock-Out (Clinical Safety P0)
* **Location:** [`app/inventory.py:93-116`](file:///f:/pharma_agent/app/inventory.py#L93-L116)
* **Code Implementation:**
  ```python
  if movement_type == "stock_out" and quantity > batch.quantity_in_stock:
      raise InventoryError(f"Cannot remove {quantity} units: only {batch.quantity_in_stock} in stock.", 409)
  if movement_type == "stock_in" and batch.expiration_date < date.today():
      raise InventoryError("Cannot add stock to an expired batch.", 409)
  ```
* **Audit Test Result:**
  ```text
  Testing stock_in on expired batch...
    stock_in blocked: Cannot add stock to an expired batch.
  Testing stock_out on expired batch...
    CRITICAL VULNERABILITY: stock_out was PERMITTED on expired batch! Token: 2e6034cd
  ```
* **Impact:** Patients can be dispensed expired pharmaceuticals if a pharmacist selects an expired batch. No validation exists at request or confirmation time.

---

### Defect S-002: Absence of FEFO (First Expired, First Out) Allocation / Warning (P1)
* **Location:** [`app/inventory.py`](file:///f:/pharma_agent/app/inventory.py)
* **Description:**
  Pharmaceutical inventory systems require FEFO discipline to prevent inventory deterioration and waste.
  Currently, `request_movement` accepts any arbitrary `batch_id` without evaluating whether another unexpired batch for the same `medicine_id` has an earlier expiration date and available stock.
* **Impact:** Pharmacists may inadvertently dispense newer stock, leaving older batches to expire on shelves (high waste rate and increased risk of near-expiry dispensation).

---

### Defect S-003: Lack of Dedicated Movement Types for Quarantine / Disposal (P1)
* **Location:** [`app/schemas.py:59`](file:///f:/pharma_agent/app/schemas.py#L59) and [`app/models.py:33`](file:///f:/pharma_agent/app/models.py#L33)
* **Code Implementation:**
  ```python
  movement_type: Literal["stock_in", "stock_out"]
  ```
  And `Batch.status` defaults to `"Active"` but has no state transition machine (`Active`, `Quarantined`, `Expired`, `Disposed`).
* **Description:**
  If an expired batch needs to be removed from the pharmacy for incineration or vendor return, the only available action is `stock_out`.
  Because `stock_out` represents standard dispensation, the audit log (`InventoryLog`) cannot distinguish between therapeutic dispensation to patients and regulatory disposal of spoiled/expired inventory.
* **Impact:** Inability to audit DEA/FDA-regulated disposal events versus sales revenue.

---

## 3. Remediation Architecture & Design Recommendations

### Recommendation 1: Strict Expired Dispensing Block with Disposal Override
1. Update `request_movement` to reject `movement_type == "stock_out"` if `batch.expiration_date < date.today()`.
2. Introduce a distinct movement type: `"disposal"` or `"quarantine_write_off"` (restricted to pharmacists or admins with a mandatory reason note).
3. Re-verify expiration in `confirm_movement` under database row lock (`with_for_update`) to prevent race conditions across midnight expiration boundaries.

### Recommendation 2: FEFO Advisory and Validation Engine
1. Query available active batches for `batch.medicine_id` ordered by `expiration_date ASC`.
2. If an active batch exists with `expiration_date < selected_batch.expiration_date` and `quantity_in_stock > 0`:
   - If not forced: reject with `409 Conflict` (or return `fefo_violation: true`) indicating batch `X` expires earlier and must be picked first.
   - If forced: require `override_fefo_reason` in payload and log warning to audit trail.
3. Provide a `/api/v1/inventory/fefo/recommend?medicine_id={id}&quantity={n}` endpoint that automatically calculates the optimal multi-batch pick list according to FEFO.

### Recommendation 3: Batch Lifecycle State Machine
1. Add automatic status updates: Batches where `expiration_date < date.today()` should automatically transition status from `Active` to `Expired`.
2. Prevent `Active` operations on batches in `Quarantined` or `Expired` states.

---

## 4. Remediation Implementation & Verification Status (COMPLETE)

The inventory safety and FEFO remediations have been implemented and verified:

1. **Strict Expired-Batch Dispensing Prevention:**
   - Implemented in [`app/inventory.py`](file:///f:/pharma_agent/app/inventory.py) in both `request_movement` and `confirm_movement` (under row-level lock).
   - Attempting `stock_out` on an expired batch now raises `InventoryError(409)` with guidance to use `disposal`.
   - Verified via [`tests/test_inventory_safety.py::test_expired_batch_stock_out_is_strictly_rejected`](file:///f:/pharma_agent/tests/test_inventory_safety.py).

2. **Dedicated `disposal` Movement Type:**
   - Extended `MovementRequest` in [`app/schemas.py`](file:///f:/pharma_agent/app/schemas.py) with `Literal["stock_in", "stock_out", "disposal"]`.
   - Handled in `request_movement` and `confirm_movement`, writing `DISPOSAL` to `InventoryLog.transaction_type`.
   - Permits pharmacists to remove expired stock legally for disposal/destruction while blocking regular sales.
   - Verified via [`tests/test_inventory_safety.py::test_expired_batch_disposal_is_permitted`](file:///f:/pharma_agent/tests/test_inventory_safety.py).

3. **FEFO Policy Enforcement & Recommendation Engine:**
   - Enforced FEFO validation in `request_movement`: If an earlier-expiring usable batch of the same medicine is in stock, `stock_out` is rejected with `409 Conflict` (FEFO Violation) unless `force_fefo=True` is explicitly passed.
   - Added endpoint `GET /api/v1/inventory/fefo/recommend` in [`app/routers/inventory.py`](file:///f:/pharma_agent/app/routers/inventory.py) returning optimal batch pick lists in order of earliest expiry.
   - Verified via [`tests/test_inventory_safety.py::test_fefo_violation_and_override`](file:///f:/pharma_agent/tests/test_inventory_safety.py) and `test_fefo_recommendation_endpoint`.

