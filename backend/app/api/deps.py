from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..control_plane import ControlPlane
from ..core.security import Perm, decode_token
from ..models import User

bearer = HTTPBearer(auto_error=False)


def get_cp(request: Request) -> ControlPlane:
    return request.app.state.cp


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.cp.sf()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@dataclass
class Principal:
    id: int
    username: str
    role: str
    permissions: frozenset[str]

    def can(self, perm: Perm) -> bool:
        return perm.value in self.permissions


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = decode_token(request.app.state.settings.jwt_secret, creds.credentials)
    except jwt.PyJWTError:
        raise unauthorized from None
    user = db.execute(select(User).where(User.username == claims["sub"])).scalar_one_or_none()
    if user is None or not user.is_active:
        raise unauthorized
    # Role and permissions are always read from the database, never trusted from the token.
    return Principal(
        id=user.id, username=user.username, role=user.role.name, permissions=frozenset(user.role.permissions)
    )


def require(perm: Perm) -> Callable[[Principal], Principal]:
    def dep(user: Principal = Depends(current_user)) -> Principal:
        if not user.can(perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm.value}")
        return user

    return dep
