"""JWT authentication with role-based access control (viewer < pharmacist < admin)."""
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import User

ROLE_RANK = {"viewer": 1, "pharmacist": 2, "admin": 3}
_bearer = HTTPBearer(auto_error=False)
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _secret() -> str:
    secret = get_settings().jwt_secret
    if not secret or len(secret) < 16:
        raise RuntimeError("JWT_SECRET must be set to a random string of at least 16 characters.")
    return secret


def create_access_token(user: User) -> tuple[str, int]:
    expires_in = get_settings().jwt_expire_minutes * 60
    payload = {
        "sub": user.username,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256"), expires_in


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username))
    # Always run one bcrypt check so response time does not reveal whether the username exists.
    valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    return user if (user and valid and user.is_active) else None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    unauthorized = HTTPException(status_code=401, detail="Invalid or missing token.", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(credentials.credentials, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise unauthorized from None
    user = session.scalar(select(User).where(User.username == payload.get("sub")))
    if user is None or not user.is_active:
        raise unauthorized
    return user  # role always comes from the database, not from the token


def require_role(minimum: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail=f"Requires role '{minimum}' or higher.")
        return user

    return dependency


def ensure_admin(session: Session) -> None:
    """Create the first admin from ADMIN_USERNAME / ADMIN_PASSWORD when the users table is empty."""
    settings = get_settings()
    if not (settings.admin_username and settings.admin_password):
        return
    if session.scalar(select(User.id).limit(1)) is None:
        session.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password), role="admin"))
        session.commit()


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())
