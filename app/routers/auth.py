from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.auth import authenticate, create_access_token, get_current_user, hash_password, require_role
from app.db import get_session
from app.models import User
from app.ratelimit import login_rate_limit
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_rate_limit)])
def login(body: LoginRequest, request: Request, session: Session = Depends(get_session)):
    user = authenticate(session, body.username, body.password)
    if user is None:
        audit.record(session, "login_failed", username=body.username[:50], request=request)
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token, expires_in = create_access_token(user)
    audit.record(session, "login", user, request=request)
    return TokenResponse(access_token=token, role=user.role, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_role("admin")), session: Session = Depends(get_session)):
    return session.scalars(select(User).order_by(User.username)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require_role("admin")),
                session: Session = Depends(get_session)):
    if session.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(status_code=409, detail="Username already exists.")
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    session.add(user)
    session.commit()
    audit.record(session, "user_created", admin, {"username": body.username, "role": body.role}, request)
    return user
