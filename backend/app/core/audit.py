"""Append-only, hash-chained audit log. Each record's hash covers its content and the
previous record's hash, so tampering with history is detectable via verify_chain()."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog
from .clock import Clock

_lock = threading.Lock()
GENESIS = "0" * 64


def _digest(prev: str, fields: dict[str, Any]) -> str:
    blob = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256((prev + blob).encode()).hexdigest()


def _fields(rec: AuditLog) -> dict[str, Any]:
    return {
        "ts": rec.ts.astimezone(UTC).isoformat() if rec.ts else None,
        "actor": rec.actor,
        "role": rec.role,
        "action": rec.action,
        "target": rec.target,
        "reason": rec.reason,
        "before": rec.before_state,
        "after": rec.after_state,
        "ai_confidence": rec.ai_confidence,
        "result": rec.result,
    }


def record(
    db: Session,
    clock: Clock,
    *,
    actor: str,
    role: str,
    action: str,
    target: str = "",
    reason: str = "",
    before: dict | None = None,
    after: dict | None = None,
    ai_confidence: float | None = None,
    result: str = "SUCCESS",
    source_ip: str | None = None,
) -> AuditLog:
    with _lock:
        last = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
        rec = AuditLog(
            ts=clock.now(),
            actor=actor,
            role=role,
            action=action,
            target=target,
            reason=reason[:2000],
            before_state=before,
            after_state=after,
            ai_confidence=ai_confidence,
            result=result,
            source_ip=source_ip,
            prev_hash=last or GENESIS,
            hash="",
        )
        rec.hash = _digest(rec.prev_hash, _fields(rec))
        db.add(rec)
        db.flush()
        return rec


def verify_chain(db: Session) -> dict[str, Any]:
    prev = GENESIS
    count = 0
    for rec in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        if rec.prev_hash != prev or _digest(prev, _fields(rec)) != rec.hash:
            return {"valid": False, "broken_at": rec.id, "checked": count}
        prev = rec.hash
        count += 1
    return {"valid": True, "checked": count}
