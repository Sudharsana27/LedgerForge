from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User


ACCESS_TOKEN_MINUTES = 30
ALGORITHM = "HS256"
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    employee_id: str
    role: str
    user_id: str | None = None


def _secret_key() -> str:
    secret = settings.secret_key
    if secret is None or len(secret.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is unavailable; configure a strong SECRET_KEY.",
        )
    return secret


def hash_password(password: str) -> str:
    if not password or len(password.encode("utf-8")) > 72:
        raise ValueError("Password must contain between 1 and 72 UTF-8 bytes")
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(user: User, *, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    return jwt.encode(
        {
            "sub": user.user_id,
            "iat": issued_at,
            "exp": expires_at,
        },
        _secret_key(),
        algorithm=ALGORITHM,
    )


def get_authenticated_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthenticatedPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = jwt.decode(
            credentials.credentials,
            _secret_key(),
            algorithms=[ALGORITHM],
        )
    except HTTPException:
        raise
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = claims.get("sub")
    user = db.get(User, user_id) if isinstance(user_id, str) else None
    if user is None or user.is_active != "Y":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = user.role.upper()
    if role not in {"ADMIN", "HR", "EMPLOYEE"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User role is not authorized",
        )
    principal = AuthenticatedPrincipal(
        employee_id=user.employee_id,
        role=role,
        user_id=user.user_id,
    )
    db.rollback()
    return principal


def require_roles(*roles: str) -> Callable:
    allowed = frozenset(role.upper() for role in roles)

    def role_dependency(
        principal: AuthenticatedPrincipal = Depends(
            get_authenticated_principal
        ),
    ) -> AuthenticatedPrincipal:
        if principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Role is not authorized for this operation",
            )
        return principal

    return role_dependency
