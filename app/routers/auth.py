from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import (
    ACCESS_TOKEN_MINUTES,
    _secret_key,
    create_access_token,
    verify_password,
)
from ..auth_schemas import AccessTokenOut, LoginInput
from ..database import get_db
from ..models import User


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=AccessTokenOut)
def login(payload: LoginInput, db: Session = Depends(get_db)) -> AccessTokenOut:
    _secret_key()
    try:
        user = db.scalar(
            select(User).where(
                func.lower(User.username) == payload.username.strip().lower()
            )
        )
        if (
            user is None
            or user.is_active != "Y"
            or not verify_password(payload.password, user.password_hash)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = create_access_token(user)
        user.last_login_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        return AccessTokenOut(
            access_token=token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_MINUTES * 60,
        )
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login could not be completed.",
        ) from exc
