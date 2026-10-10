from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app import audit, inventory
from app.auth import require_role
from app.db import get_session
from app.models import User
from app.schemas import FefoRecommendationOut, MovementRequest, PendingMovementOut

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/batches")
def batches(_: User = Depends(require_role("viewer")), session: Session = Depends(get_session)):
    return inventory.list_batches(session)


@router.get("/alerts")
def alerts(days: int = Query(60, ge=1, le=365, description="Expiry look-ahead window in days"),
           _: User = Depends(require_role("viewer")), session: Session = Depends(get_session)):
    return inventory.get_alerts(session, days=days)


@router.get("/report/daily")
def daily_report(_: User = Depends(require_role("viewer")), session: Session = Depends(get_session)):
    return inventory.daily_report(session)


@router.get("/fefo/recommend", response_model=FefoRecommendationOut)
def fefo_recommendation(medicine_id: int = Query(..., ge=1, description="Medicine ID"),
                        quantity: int = Query(..., ge=1, le=100_000, description="Quantity required"),
                        _: User = Depends(require_role("viewer")), session: Session = Depends(get_session)):
    """Calculate the optimal batches to dispense based on First Expired, First Out (FEFO)."""
    return inventory.get_fefo_recommendation(session, medicine_id, quantity)


@router.post("/movements", response_model=PendingMovementOut, status_code=201)
def request_movement(body: MovementRequest, request: Request, user: User = Depends(require_role("pharmacist")),
                     session: Session = Depends(get_session)):
    """Step 1 of 2: validate the movement and get a confirmation token. Stock is NOT changed yet."""
    pending = inventory.request_movement(session, user, body.batch_id, body.movement_type, body.quantity,
                                         body.note, force_fefo=body.force_fefo)
    audit.record(session, "movement_requested", user, pending.payload | {"type": body.movement_type}, request)
    return PendingMovementOut(confirmation_token=pending.token, summary=pending.payload["summary"],
                              expires_at=pending.expires_at)


@router.post("/movements/{token}/confirm")
def confirm_movement(token: str, request: Request, user: User = Depends(require_role("pharmacist")),
                     session: Session = Depends(get_session)):
    """Step 2 of 2: apply the movement and write the inventory log."""
    result = inventory.confirm_movement(session, user, token)
    audit.record(session, "movement_confirmed", user, result, request)
    return result