from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

import bcrypt
import jwt


class RoleName(StrEnum):
    ADMIN = "ADMIN"
    SRE = "SRE"
    DEVELOPER = "DEVELOPER"
    VIEWER = "VIEWER"


class Perm(StrEnum):
    READ = "read"
    AI_INVESTIGATE = "ai:investigate"
    INCIDENT_UPDATE = "incident:update"
    REMEDIATION_PROPOSE = "remediation:propose"
    REMEDIATION_APPROVE = "remediation:approve"
    REMEDIATION_APPROVE_HIGH = "remediation:approve_high"
    SIMULATOR_RUN = "simulator:run"
    DEPLOY = "deployment:create"
    AUDIT_READ = "audit:read"
    SETTINGS_WRITE = "settings:write"
    USERS_MANAGE = "users:manage"


ROLE_PERMISSIONS: dict[RoleName, list[Perm]] = {
    RoleName.VIEWER: [Perm.READ],
    RoleName.DEVELOPER: [Perm.READ, Perm.AI_INVESTIGATE, Perm.REMEDIATION_PROPOSE],
    RoleName.SRE: [
        Perm.READ,
        Perm.AI_INVESTIGATE,
        Perm.INCIDENT_UPDATE,
        Perm.REMEDIATION_PROPOSE,
        Perm.REMEDIATION_APPROVE,
        Perm.SIMULATOR_RUN,
        Perm.DEPLOY,
        Perm.AUDIT_READ,
    ],
    RoleName.ADMIN: list(Perm),
}

ROLE_DESCRIPTIONS = {
    RoleName.ADMIN: "Full control including settings, users, and HIGH-risk remediation approval",
    RoleName.SRE: "Operate incidents, approve LOW/MEDIUM remediation, run failure simulations",
    RoleName.DEVELOPER: "Read telemetry, run AI investigations, propose remediation",
    RoleName.VIEWER: "Read-only access",
}


def hash_password(password: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# Constant-time dummy hash so unknown usernames cost the same as wrong passwords.
DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(rounds=12)).decode()


def create_token(secret: str, username: str, role: str, ttl_minutes: int, now: datetime) -> str:
    payload = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "iss": "cloudops-ai",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> dict:
    return jwt.decode(
        token, secret, algorithms=["HS256"], issuer="cloudops-ai", options={"require": ["exp", "sub", "iss"]}
    )
