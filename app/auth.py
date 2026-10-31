from dataclasses import dataclass

from fastapi import HTTPException, status


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    employee_id: str
    role: str


def get_authenticated_principal() -> AuthenticatedPrincipal:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required",
        headers={"WWW-Authenticate": "Bearer"},
    )
