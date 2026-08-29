"""Pull the latest farm frustration snapshot from Component 3 (gaming-service).

Sachini's open API:
    GET {GAMING_FRUSTRATION_API_BASE}/api/engagement/frustration?studentId=...

Default local host: http://127.0.0.1:8002
Score is 0–100; we normalize to 0–1 for tutor tone.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_GAMING_API_BASE = "http://127.0.0.1:8002"
_TIMEOUT_S = 1.8


def gaming_api_base() -> str:
    raw = (
        os.environ.get("GAMING_FRUSTRATION_API_BASE")
        or os.environ.get("GAMING_API_BASE")
        or DEFAULT_GAMING_API_BASE
    )
    return str(raw).strip().rstrip("/")


def _normalize_unit_score(raw: Any) -> Optional[float]:
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    if score > 1.0:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def fetch_gaming_frustration(
    student_id: str,
    *,
    session_id: Optional[str] = None,
    limit: int = 1,
) -> Optional[dict[str, Any]]:
    """Return a normalized snapshot or None if gaming is unreachable / empty."""
    uid = str(student_id or "").strip()
    if not uid:
        return None

    params: dict[str, str] = {"studentId": uid, "limit": str(max(1, min(50, int(limit or 1))))}
    sid = str(session_id or "").strip()
    if sid:
        params["sessionId"] = sid

    url = f"{gaming_api_base()}/api/engagement/frustration?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("ok") is False or payload.get("skipped"):
        return None

    unit = _normalize_unit_score(
        payload.get("frustrationScore")
        if payload.get("frustrationScore") is not None
        else payload.get("frustration_score")
    )
    if unit is None:
        return None

    return {
        "user_id": uid,
        "frustration_score": unit,
        "frustration_score_100": float(payload.get("frustrationScore") or payload.get("frustration_score") or 0),
        "frustration_level_gaming": payload.get("frustrationLevel") or payload.get("frustration_level"),
        "session_id": payload.get("sessionId") or payload.get("session_id") or sid or None,
        "recorded_at": payload.get("recordedAt") or payload.get("recorded_at"),
        "source": "gaming_service_get",
        "raw": payload,
    }
