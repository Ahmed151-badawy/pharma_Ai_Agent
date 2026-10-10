from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["viewer", "pharmacist", "admin"]


def _check_password(value: str) -> str:
    if len(value.encode()) > 72:  # bcrypt limit
        raise ValueError("Password must be at most 72 bytes.")
    return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    expires_in: int


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=72)
    role: Role = "viewer"

    _pw = field_validator("password")(_check_password)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    is_active: bool


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ChatResponse(BaseModel):
    query: str
    response: str
    session_id: str
    citations: list[dict[str, Any]] = []
    tools_used: list[str] = []


class MovementRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=50)
    movement_type: Literal["stock_in", "stock_out", "disposal"]
    quantity: int = Field(gt=0, le=100_000)
    note: str | None = Field(default=None, max_length=200)
    force_fefo: bool = False


class FefoBatchAllocation(BaseModel):
    batch_id: str
    expiration_date: str
    available_stock: int
    quantity_to_dispense: int


class FefoRecommendationOut(BaseModel):
    medicine_id: int
    requested_quantity: int
    allocated_quantity: int
    sufficient_stock: bool
    batches: list[FefoBatchAllocation]



class PendingMovementOut(BaseModel):
    confirmation_token: str
    summary: str
    expires_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    pages: int
    chunks: int
    uploaded_by: str
    created_at: datetime
