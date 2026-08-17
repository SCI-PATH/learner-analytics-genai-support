"""
FastAPI app exposing Socratic hint endpoints.

**Mastery model:** One ``ScienceBKT`` instance (via ``get_shared_bkt_engine()``).
Per learner and skill there is a **single** ``student_state`` trajectory.
``POST /api/v1/assessment-submit`` applies **ground-truth** ``is_correct``;
``/tutor/hint*`` may apply dialogue-derived updates per ``TUTOR_BKT_POLICY`` in
``socratic_tutor`` (default strict; ``quiz_only`` disables chat-driven BKT).

Run:
    uvicorn main:app --reload
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Path as ApiPath
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from bkt_engine import ScienceBKT
from postgres_store import (
    fetch_assessment_attempts_for_learner,
    fetch_frustration_scores_for_learner,
    fetch_tutor_turns_for_learner,
    insert_assessment_attempt,
    insert_frustration_cue,
    insert_tutor_turn,
    list_distinct_learner_ids,
    postgres_configured,
)
from socratic_tutor import (
    generate_socratic_hint,
    generate_socratic_hint_auto_topic,
    get_shared_bkt_engine,
    upsert_frustration_signal,
)

app = FastAPI(
    title="Socratic Tutor API",
    description=(
        "Component 4 — Learner Profile Analytics & GenAI Support.\n\n"
        "**Question Engine / Content Gen (read mastery):** "
        "`GET /api/v1/mastery/{user_id}/{topic_id}` returns current BKT P(L) and "
        "`mastery_category` (`basic` / `intermediate` / `advanced`) without recording an attempt.\n\n"
        "**Question Engine (write attempt):** `POST /api/v1/assessment-submit` records a scored "
        "quiz item, updates BKT, and returns the new P(L) + category.\n\n"
        "**Student focus areas:** `GET /api/v1/analytics/student-focus-areas/{user_id}` lists "
        "at-risk topics for one learner (student profile).\n\n"
        "Interactive docs: `/docs` (Swagger) and `/redoc`."
    ),
    version="0.1.0",
    openapi_tags=[
        {
            "name": "Health",
            "description": "Service health check.",
        },
        {
            "name": "Mastery",
            "description": (
                "BKT mastery read/update. Question Engine writes scored attempts via "
                "**POST /api/v1/assessment-submit**. Read current P(L) with "
                "**GET /api/v1/mastery/{user_id}/{topic_id}**."
            ),
        },
        {
            "name": "Engagement",
            "description": (
                "Frustration cues from Component 3. Stored in Postgres "
                "``learner_analytics.frustration_cues``; steers tutor tone on the next hint."
            ),
        },
        {
            "name": "Tutor",
            "description": (
                "Socratic chatbot hint endpoints. Each successful turn is persisted to "
                "``learner_analytics.tutor_turns``. BKT may update per ``TUTOR_BKT_POLICY``."
            ),
        },
        {
            "name": "Analytics",
            "description": (
                "Teacher dashboard (matrix, at-risk) and student profile / focus areas."
            ),
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lightweight in-memory analytics signals for at-risk trend checks.
_signal_history: dict[tuple[str, str], deque[float]] = defaultdict(lambda: deque(maxlen=20))
_latest_topic_by_user: dict[str, str] = {}
_frustration_history: dict[tuple[str, str], deque[float]] = defaultdict(lambda: deque(maxlen=50))
_chat_history_by_user: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=100))
_assessment_attempts_by_user: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=500))
QuestionType = Literal["MCQ", "ShortAnswer", "MultiBlank", "TrueFalse"]
DistractorTag = Literal["NEAR_MISS", "MISCONCEPTION", "COMPLETE_MISS"]
ErrorCategory = Literal[
    "NO_ERROR",
    "SPELLING_GRAMMAR_ERROR",
    "MISSING_KEYWORDS",
    "CONCEPTUAL_MISCONCEPTION",
    "COMPLETELY_IRRELEVANT",
    "PARTIAL_MASTERY",
    "FULL_MISCONCEPTION",
]
_QUESTION_TYPE_ALIASES = {
    "SHORT_ANSWER": "ShortAnswer",
    "SHORTANSWER": "ShortAnswer",
    "MULTI_BLANK": "MultiBlank",
    "MULTIBLANK": "MultiBlank",
    "TRUE_FALSE": "TrueFalse",
    "TRUEFALSE": "TrueFalse",
}
MasteryCategory = Literal["basic", "intermediate", "advanced"]
_SLIP_HIGH_THRESHOLD = 0.15
_MASTERY_LOW_THRESHOLD = 0.45
_MASTERY_CRITICAL_THRESHOLD = 0.20
# Shared bands for tutor hint mode, dashboard heatmap, and teammate DDA.
_MASTERY_BASIC_MAX = 0.50
_MASTERY_ADVANCED_MIN = 0.80


def _mastery_category_from_pl(mastery: float) -> MasteryCategory:
    """Map BKT P(L) to a learner category for this (user, topic)."""
    p = float(mastery)
    if p < _MASTERY_BASIC_MAX:
        return "basic"
    if p >= _MASTERY_ADVANCED_MIN:
        return "advanced"
    return "intermediate"


def _mastery_category_payload(mastery: float) -> dict[str, Any]:
    return {
        "mastery_category": _mastery_category_from_pl(mastery),
        "mastery_category_thresholds": {
            "basic": f"P(L) < {_MASTERY_BASIC_MAX:.2f}",
            "intermediate": f"{_MASTERY_BASIC_MAX:.2f} <= P(L) < {_MASTERY_ADVANCED_MIN:.2f}",
            "advanced": f"P(L) >= {_MASTERY_ADVANCED_MIN:.2f}",
        },
    }
_LIVE_STATE_DB = PROJECT_ROOT / "live_state_events.db"
_INTERACTION_LOG_PATH = PROJECT_ROOT / "interaction_logs.json"


def _canonicalize_question_type(value: Any) -> Optional[str]:
    """Map Question Engine aliases (e.g. SHORT_ANSWER) onto canonical bank values."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw in {"MCQ", "ShortAnswer", "MultiBlank", "TrueFalse"}:
        return raw
    mapped = _QUESTION_TYPE_ALIASES.get(raw.upper().replace("-", "_").replace(" ", "_"))
    if mapped:
        return mapped
    raise ValueError(
        "question_type must be MCQ, ShortAnswer, MultiBlank, or TrueFalse "
        "(SHORT_ANSWER is accepted as an alias of ShortAnswer)"
    )


def _append_signal(user_id: str, topic_id: str, value: float) -> None:
    key = (str(user_id), str(topic_id))
    _signal_history[key].append(float(max(0.0, min(1.0, value))))
    _latest_topic_by_user[str(user_id)] = str(topic_id)


def _init_persistence() -> None:
    with sqlite3.connect(_LIVE_STATE_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _persist_event(event_type: str, payload: dict[str, Any]) -> None:
    with sqlite3.connect(_LIVE_STATE_DB) as conn:
        conn.execute(
            "INSERT INTO state_events (event_type, payload_json, created_at) VALUES (?, ?, ?)",
            (
                str(event_type),
                json.dumps(payload, ensure_ascii=True),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()


def _append_interaction_log(
    *,
    user_id: str,
    topic_id: str,
    interaction_score: Optional[float],
    endpoint: str,
    frustration_metadata: Optional[dict[str, Any]] = None,
) -> None:
    entry: dict[str, Any] = {
        "user_id": str(user_id),
        "topic_id": str(topic_id),
        "interaction_score": (
            None if interaction_score is None else float(max(0.0, min(1.0, interaction_score)))
        ),
        "timestamp": datetime.now(UTC).isoformat(),
        "endpoint": str(endpoint),
    }
    if frustration_metadata:
        for key, value in frustration_metadata.items():
            if value is not None:
                entry[key] = value
    rows: list[dict[str, Any]] = []
    if _INTERACTION_LOG_PATH.exists():
        try:
            loaded = json.loads(_INTERACTION_LOG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                rows = loaded
        except (json.JSONDecodeError, OSError):
            rows = []
    rows.append(entry)
    if len(rows) > 10000:
        rows = rows[-10000:]
    _INTERACTION_LOG_PATH.write_text(
        json.dumps(rows, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def _load_interaction_logs_for_user(user_id: str, limit: int = 10) -> list[dict[str, Any]]:
    if not _INTERACTION_LOG_PATH.exists():
        return []
    try:
        loaded = json.loads(_INTERACTION_LOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(loaded, list):
        return []
    rows = [r for r in loaded if isinstance(r, dict) and str(r.get("user_id")) == str(user_id)]
    rows.sort(key=lambda r: str(r.get("timestamp") or ""))
    return rows[-max(1, int(limit)) :]


def _load_persisted_events() -> list[tuple[str, dict[str, Any]]]:
    if not _LIVE_STATE_DB.exists():
        return []
    events: list[tuple[str, dict[str, Any]]] = []
    with sqlite3.connect(_LIVE_STATE_DB) as conn:
        rows = conn.execute(
            "SELECT event_type, payload_json FROM state_events ORDER BY id ASC"
        ).fetchall()
    for event_type, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append((str(event_type), payload))
    return events


def _hydrate_live_state_from_db() -> None:
    events = _load_persisted_events()
    if not events:
        return
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    try:
        skip_bkt_replay = postgres_configured()
    except Exception:
        skip_bkt_replay = False
    for event_type, payload in events:
        if event_type == "assessment_submit":
            uid = str(payload.get("user_id") or "")
            topic = str(payload.get("topic_id") or "")
            if "is_correct" in payload:
                label = 1 if bool(payload.get("is_correct")) else 0
            else:
                label = int(payload.get("label") or 0)
            if not uid or not topic:
                continue
            response_time = payload.get("response_time_s")
            try:
                response_time_s = float(response_time) if response_time is not None else None
            except (TypeError, ValueError):
                response_time_s = None
            if not skip_bkt_replay:
                try:
                    engine.predict_update(
                        uid, topic, label, response_time_s, persist=False
                    )
                except ValueError:
                    continue
            _append_signal(uid, topic, float(label))
            _record_assessment_attempt(payload)
        elif event_type == "frustration_cue":
            uid = str(payload.get("user_id") or "")
            topic = str(payload.get("topic_id") or "")
            score = float(payload.get("frustration_score") or 0.0)
            source = str(payload.get("source") or "engagement_module")
            if not uid or not topic:
                continue
            recorded_at_raw = payload.get("recorded_at")
            signal = upsert_frustration_signal(
                user_id=uid,
                topic_id=topic,
                frustration_score=score,
                source=source,
                recorded_at=(
                    datetime.fromisoformat(str(recorded_at_raw).replace("Z", "+00:00"))
                    if recorded_at_raw
                    else None
                ),
            )
            _frustration_history[(uid, topic)].append(float(signal.frustration_score))
        elif event_type == "chat_turn":
            uid = str(payload.get("user_id") or "")
            topic = str(payload.get("topic_id") or "")
            student_msg = str(payload.get("student_message") or "")
            tutor_msg = str(payload.get("tutor_hint") or "")
            ts = str(payload.get("timestamp") or datetime.now(UTC).isoformat())
            if not uid or not topic:
                continue
            _chat_history_by_user[uid].append(
                {
                    "topic_id": topic,
                    "student_message": student_msg,
                    "tutor_hint": tutor_msg,
                    "interaction_score": payload.get("interaction_score"),
                    "critical_confusion": bool(payload.get("critical_confusion") is True),
                    "timestamp": ts,
                }
            )
            _latest_topic_by_user[uid] = topic


def _has_negative_velocity(user_id: str, topic_id: str) -> bool:
    values = list(_signal_history.get((str(user_id), str(topic_id)), []))
    if len(values) < 3:
        return False
    a, b, c = values[-3:]
    return bool(a > b > c)


def _recent_signal_avg(user_id: str, topic_id: str, window: int = 5) -> Optional[float]:
    vals = list(_signal_history.get((str(user_id), str(topic_id)), []))
    if not vals:
        return None
    tail = vals[-max(1, int(window)) :]
    return float(sum(tail) / len(tail))


def _risk_criteria_payload() -> dict[str, Any]:
    return {
        "low_mastery_threshold": _MASTERY_LOW_THRESHOLD,
        "critical_mastery_threshold": _MASTERY_CRITICAL_THRESHOLD,
        "recent_performance_threshold": 0.4,
        "negative_velocity_rule": "last_3_signals_strictly_decreasing",
        "alert_rule": "at_least_2_of_3_signals(low_mastery, negative_velocity, weak_recent_performance)",
        "immediate_override_rule": "mastery_below_critical_and_weak_recent_performance",
    }


def _compose_topic_risk_alert(
    *,
    student_id: str,
    topic_id: str,
    mastery: float,
    low_mastery: bool,
    neg_velocity: bool,
    weak_recent_perf: bool,
    recent_signal_tail: list[float],
    recent_performance_avg: Optional[float],
) -> Optional[dict[str, Any]]:
    """
    Shared at-risk / focus-area rule for one (student, topic).

    Returns None when fewer than 2 of the 3 primary signals fire.
    """
    signal_count = int(low_mastery) + int(neg_velocity) + int(weak_recent_perf)
    if signal_count < 2:
        return None

    reasons: list[str] = []
    risk_score = 0
    if low_mastery:
        reasons.append("Low Mastery")
        risk_score += 40
    if neg_velocity:
        reasons.append("Declining Mastery Velocity")
        risk_score += 30
    if weak_recent_perf:
        reasons.append("Weak Recent Performance")
        risk_score += 30
    if mastery < _MASTERY_CRITICAL_THRESHOLD and weak_recent_perf:
        reasons.append("Critical Low Mastery")
        risk_score = max(risk_score, 85)

    return {
        "student_id": str(student_id),
        "topic_id": str(topic_id),
        "mastery_probability": round(float(mastery), 4),
        "mastery_category": _mastery_category_from_pl(mastery),
        "negative_velocity": bool(neg_velocity),
        "recent_signal_tail": [round(float(v), 4) for v in recent_signal_tail],
        "recent_performance_avg": (
            None if recent_performance_avg is None else round(float(recent_performance_avg), 4)
        ),
        "signals_triggered": signal_count,
        "signals": {
            "low_mastery": bool(low_mastery),
            "negative_velocity": bool(neg_velocity),
            "weak_recent_performance": bool(weak_recent_perf),
        },
        "risk_score": int(min(100, max(0, risk_score))),
        "reason": "; ".join(reasons),
    }


def _build_student_focus_areas(
    user_id: str,
    *,
    topic_ids: Optional[list[str]] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Return all at-risk topics for one learner (student focus areas).

    Unlike the classroom at-risk endpoint (one current topic per student), this
    scans every topic the learner has evidence on from live runtime + Postgres state.
    """
    uid = str(user_id)
    focus_areas: list[dict[str, Any]] = []

    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    all_topics = sorted(engine.skill_map.keys())
    topic_pool = [t for t in (topic_ids if topic_ids else all_topics) if t in engine.skill_map]

    live_topics = {
        str(row.get("topic_id") or "")
        for row in _live_attempts_for_user(uid)
        if row.get("topic_id")
    }
    signal_topics = {
        tid for (u, tid), vals in _signal_history.items() if u == uid and vals
    }
    state_topics = {
        tid
        for (u, tid), state in engine.student_state.items()
        if u == uid and isinstance(state, dict) and int(state.get("attempts", 0)) > 0
    }
    topics_with_evidence = sorted(
        (live_topics | signal_topics | state_topics) & set(topic_pool)
    )

    for topic in topics_with_evidence:
        mastery = float(engine.get_current_mastery_probability(uid, topic))
        low_mastery = mastery < _MASTERY_LOW_THRESHOLD
        neg_velocity = _has_negative_velocity(uid, topic)
        recent_avg = _recent_signal_avg(uid, topic, window=5)
        weak_recent_perf = (recent_avg is not None) and (recent_avg < 0.4)
        alert = _compose_topic_risk_alert(
            student_id=uid,
            topic_id=topic,
            mastery=mastery,
            low_mastery=low_mastery,
            neg_velocity=neg_velocity,
            weak_recent_perf=weak_recent_perf,
            recent_signal_tail=list(_signal_history.get((uid, topic), []))[-3:],
            recent_performance_avg=recent_avg,
        )
        if alert:
            focus_areas.append(alert)

    focus_areas.sort(key=lambda a: a["risk_score"], reverse=True)
    return focus_areas, {
        "known_topics": all_topics,
        "topics_scanned": len(topics_with_evidence),
    }


def _record_tutor_turn(
    *,
    user_id: str,
    topic_id: str,
    student_message: str,
    tutor_message: str,
    interaction_score: Optional[float] = None,
    endpoint: str = "/tutor/hint",
    persona_id: Optional[str] = None,
    hint_mode: Optional[str] = None,
    topic_inferred: bool = False,
    bkt_updated: bool = False,
    frustration_metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Persist one tutor turn to memory, SQLite, and Postgres (when configured)."""
    score_val = (
        None
        if interaction_score is None
        else float(max(0.0, min(1.0, float(interaction_score))))
    )
    frustration_metadata = frustration_metadata or {}
    record: dict[str, Any] = {
        "user_id": str(user_id),
        "topic_id": str(topic_id),
        "student_message": str(student_message),
        "tutor_hint": str(tutor_message),
        "interaction_score": score_val,
        "critical_confusion": bool(score_val is not None and score_val < 0.30),
        "timestamp": datetime.now(UTC).isoformat(),
        "endpoint": endpoint,
        "persona_id": persona_id,
        "hint_mode": hint_mode,
        "topic_inferred": bool(topic_inferred),
        "bkt_updated": bool(bkt_updated),
        "frustration_level_used": frustration_metadata.get("frustration_level_used"),
        "frustration_source_tag": frustration_metadata.get("source_tag"),
        "frustration_effective_score": frustration_metadata.get("effective_score"),
    }
    _chat_history_by_user[str(user_id)].append(
        {
            "topic_id": record["topic_id"],
            "student_message": record["student_message"],
            "tutor_hint": record["tutor_hint"],
            "interaction_score": record["interaction_score"],
            "critical_confusion": record["critical_confusion"],
            "timestamp": record["timestamp"],
        }
    )
    _latest_topic_by_user[str(user_id)] = str(topic_id)
    _persist_event("chat_turn", record)
    postgres_result = insert_tutor_turn(record)
    return {"record": record, "postgres": postgres_result}


def _load_tutor_turns_for_user(user_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Engagement timeline rows; prefers Postgres when configured."""
    if postgres_configured():
        db_rows = fetch_tutor_turns_for_learner(str(user_id), limit=limit)
        if db_rows:
            return db_rows
    return _load_interaction_logs_for_user(user_id, limit=limit)


def _load_chat_tail_for_user(user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Last N chat turns for profile review; prefers Postgres when configured."""
    if postgres_configured():
        db_rows = fetch_tutor_turns_for_learner(str(user_id), limit=limit)
        if db_rows:
            return [
                {
                    "topic_id": row.get("topic_id"),
                    "student_message": row.get("student_message"),
                    "tutor_hint": row.get("tutor_hint"),
                    "interaction_score": row.get("interaction_score"),
                    "critical_confusion": row.get("critical_confusion"),
                    "timestamp": row.get("timestamp"),
                }
                for row in db_rows[-limit:]
            ]
    return list(_chat_history_by_user.get(str(user_id), []))[-limit:]


def _load_frustration_values_for_user(user_id: str) -> list[float]:
    """Frustration cue scores for engagement metrics; prefers Postgres."""
    if postgres_configured():
        db_vals = fetch_frustration_scores_for_learner(str(user_id))
        if db_vals:
            return db_vals
    return [
        v
        for (uid, _topic), seq in _frustration_history.items()
        if uid == str(user_id)
        for v in seq
    ]


def _normalize_assessment_attempt(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize persisted or incoming assessment payloads into a canonical attempt record."""
    uid = str(payload.get("user_id") or "")
    topic = str(payload.get("topic_id") or "")
    if "is_correct" in payload:
        is_correct = bool(payload["is_correct"])
    else:
        is_correct = bool(int(payload.get("label") or 0))
    record: dict[str, Any] = {
        "user_id": uid,
        "topic_id": topic,
        "is_correct": is_correct,
        "label": 1 if is_correct else 0,
        "timestamp": str(payload.get("timestamp") or datetime.now(UTC).isoformat()),
    }
    optional_fields = (
        "question_type",
        "distractor_tag",
        "distractor_label",
        "similarity_score",
        "error_category",
        "detailed_explanation",
        "missed_blanks",
        "response_time_s",
        "difficulty_level",
        "subtopic_id",
        "question_id",
        "chosen_distractor_text",
        "source",
        "updated_mastery_probability",
        "mastery_category",
    )
    for key in optional_fields:
        if payload.get(key) is not None:
            record[key] = payload[key]
    return record


def _record_assessment_attempt(payload: dict[str, Any]) -> dict[str, Any]:
    record = _normalize_assessment_attempt(payload)
    uid = str(record.get("user_id") or "")
    if uid:
        _assessment_attempts_by_user[uid].append(record)
    return record


def _misconception_cloud_label(attempt: dict[str, Any]) -> Optional[str]:
    if bool(attempt.get("is_correct")):
        return None
    label = str(attempt.get("distractor_label") or "").strip()
    if label:
        return label
    chosen = str(attempt.get("chosen_distractor_text") or "").strip()
    if chosen:
        return chosen[:80] + ("..." if len(chosen) > 80 else "")
    tag = str(attempt.get("distractor_tag") or "").strip()
    if tag:
        return tag.replace("_", " ").title()
    return None


def _live_distractor_counts(user_id: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for attempt in _assessment_attempts_by_user.get(str(user_id), []):
        cloud_label = _misconception_cloud_label(attempt)
        if cloud_label:
            counts[cloud_label] += 1
    return dict(counts)


def _live_attempts_for_user(user_id: str) -> list[dict[str, Any]]:
    """Assessment attempts from in-memory runtime; prefers Postgres when configured."""
    if postgres_configured():
        db_rows = fetch_assessment_attempts_for_learner(str(user_id))
        if db_rows:
            return db_rows
    return list(_assessment_attempts_by_user.get(str(user_id), []))


def _known_learner_ids(student_ids: Optional[list[str]] = None) -> list[str]:
    """Union of learners seen in runtime state, events, and Postgres."""
    ids: set[str] = set(_latest_topic_by_user.keys())
    ids.update(str(u) for u, _ in get_shared_bkt_engine().student_state.keys())
    if postgres_configured():
        ids.update(list_distinct_learner_ids())
    if student_ids:
        allowed = set(student_ids)
        ids = {u for u in ids if u in allowed}
    return sorted(ids)


class ChatTurn(BaseModel):
    """Single message in chronological order (excludes ``student_answer``)."""

    role: Literal["user", "assistant"]
    content: str = Field("", max_length=8000)


class TutorHintRequest(BaseModel):
    user_id: str = Field(..., description="Student identifier")
    topic_id: str = Field(..., description="Curriculum topic id, e.g. G6_S8_ELE_CONDINS")
    student_answer: str = Field(..., description="Learner's latest question/attempt text")
    conversation_history: Optional[list[ChatTurn]] = Field(
        None,
        description="Earlier chat turns oldest→newest; omit the latest student line (it's student_answer)",
    )
    context_k: int = Field(4, ge=1, le=10, description="Number of retrieved textbook chunks")
    persona_id: Optional[str] = Field(
        None,
        description=(
            "Tutor persona: practical_encourager, analytical_coach, or curious_explorer. "
            "If omitted, server uses TUTOR_DEFAULT_PERSONA or rotates randomly per turn."
        ),
    )


class TutorHintAutoTopicRequest(BaseModel):
    user_id: str = Field(..., description="Student identifier")
    student_answer: str = Field(..., description="Learner's latest question/attempt text")
    topic_id: Optional[str] = Field(
        None,
        description="Optional topic id override. If omitted, server infers topic from question text.",
    )
    conversation_history: Optional[list[ChatTurn]] = Field(
        None,
        description="Earlier turns for continuity (same semantics as TutorHintRequest)",
    )
    context_k: int = Field(4, ge=1, le=10, description="Number of retrieved textbook chunks")
    persona_id: Optional[str] = Field(
        None,
        description=(
            "Tutor persona: practical_encourager, analytical_coach, or curious_explorer. "
            "If omitted, server uses TUTOR_DEFAULT_PERSONA or rotates randomly per turn."
        ),
    )


class AssessmentSubmitRequest(BaseModel):
    """Verified quiz outcome; updates the same BKT state as the tutor.

    BKT always updates from ``is_correct`` (0/1). ``question_type`` is metadata
    only — MCQ, ShortAnswer, MultiBlank, and TrueFalse all drive the same engine.
    """

    user_id: str = Field(..., description="Student identifier")
    topic_id: str = Field(..., description="Curriculum topic / skill id, e.g. G6_C8_ELE_CIRCUITS")
    is_correct: bool = Field(..., description="Ground-truth correctness for this assessment item")
    question_type: Optional[QuestionType] = Field(
        None,
        description=(
            "Question Engine item type: MCQ, ShortAnswer, MultiBlank, or TrueFalse. "
            "SHORT_ANSWER is accepted as an alias of ShortAnswer."
        ),
    )
    distractor_tag: Optional[DistractorTag] = Field(
        None, description="Wrong MCQ error category: NEAR_MISS, MISCONCEPTION, or COMPLETE_MISS"
    )
    distractor_label: Optional[str] = Field(
        None, description="Short misconception phrase for Misconception Cloud aggregation"
    )
    similarity_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="ShortAnswer / MultiBlank closeness to marking scheme (0–1)",
    )
    error_category: Optional[ErrorCategory] = Field(
        None,
        description=(
            "Diagnostic class from Question Engine. ShortAnswer: NO_ERROR, "
            "SPELLING_GRAMMAR_ERROR, MISSING_KEYWORDS, CONCEPTUAL_MISCONCEPTION, "
            "COMPLETELY_IRRELEVANT. MultiBlank: NO_ERROR, PARTIAL_MASTERY, FULL_MISCONCEPTION."
        ),
    )
    detailed_explanation: Optional[str] = Field(
        None, description="1–2 sentence explanation (wrong ShortAnswer / TrueFalse)"
    )
    missed_blanks: Optional[dict[str, str]] = Field(
        None, description='MultiBlank missed slots, e.g. {"1": "base"}'
    )
    response_time_s: Optional[float] = Field(None, ge=0.0, description="Seconds taken to answer")
    difficulty_level: Optional[float] = Field(None, description="Item difficulty on question-engine scale")
    subtopic_id: Optional[str] = Field(None, description="Optional finer curriculum label")
    question_id: Optional[str] = Field(None, description="Stable question item id for audit/dedupe")
    chosen_distractor_text: Optional[str] = Field(
        None, description="Full text of chosen wrong MCQ option when label is omitted"
    )
    source: Optional[str] = Field(None, description="Calling module identifier, e.g. question_engine_v1")

    @field_validator("question_type", mode="before")
    @classmethod
    def _normalize_question_type(cls, value: Any) -> Optional[str]:
        return _canonicalize_question_type(value)

    @field_validator("error_category", "detailed_explanation", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("missed_blanks", mode="before")
    @classmethod
    def _normalize_missed_blanks(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        return value


class FrustrationCueSubmitRequest(BaseModel):
    """Engagement module cue for sentiment-aware tutor tone adaptation."""

    user_id: str = Field(..., description="Student identifier")
    topic_id: str = Field(..., description="Curriculum topic / skill id")
    frustration_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized frustration intensity from 0.0 (calm) to 1.0 (high frustration)",
    )
    source: str = Field(
        "engagement_module",
        description="Producer identifier (e.g., engagement_module_v1)",
    )


class MasteryMatrixRequest(BaseModel):
    """Request payload for classroom mastery matrix (live BKT + Postgres state)."""

    student_ids: list[str] = Field(..., min_length=1, description="List of learner IDs")
    topic_ids: list[str] = Field(..., min_length=1, description="List of topic/skill IDs")


class AtRiskStudentsRequest(BaseModel):
    """Optional filter controls for at-risk analytics."""

    student_ids: Optional[list[str]] = Field(None, description="Restrict scan to these students")
    topic_ids: Optional[list[str]] = Field(None, description="Restrict scan to these topics")


@app.get("/health", tags=["Health"], summary="Health check")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def _startup_init() -> None:
    _init_persistence()
    _hydrate_live_state_from_db()
    _warmup_heavy_dependencies()


def _warmup_heavy_dependencies() -> None:
    """Load RAG embeddings + BKT skill map once at startup (avoids first-request stall)."""
    try:
        engine = get_shared_bkt_engine()
        if not engine.skill_map:
            engine.initialize_skills()
        if engine.params_source == "postgres":
            engine.preload_calibrated_skill_params()
    except Exception:
        pass
    if os.environ.get("TUTOR_WARMUP_RAG", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }:
        try:
            from knowledge_base import retrieve_context

            retrieve_context("G6_C7_MAG_POLES", k=1)
        except Exception:
            pass


def _frustration_metadata_from_result(result: dict[str, Any]) -> dict[str, Any]:
    """Extract Epic 7 audit fields for interaction_logs.json."""
    keys = (
        "frustration_raw",
        "effective_score",
        "source_tag",
        "persona_id_used",
        "frustration_internal_score",
        "frustration_external_effective",
        "frustration_fused_score",
        "frustration_level_used",
    )
    return {k: result.get(k) for k in keys if result.get(k) is not None}


@app.post(
    "/tutor/hint",
    tags=["Tutor"],
    summary="Socratic hint (explicit topic)",
    response_description="Hint text, interaction score, optional BKT update, Postgres tutor_turn row",
)
def tutor_hint(req: TutorHintRequest) -> dict[str, Any]:
    """
    Explicit topic flow:
    client provides user_id + topic_id + student_answer.

    **BKT:** Dialogue updates follow ``TUTOR_BKT_POLICY`` (strict / quiz_only / legacy).
    Use ``conversation_history`` so the model can treat replies as continuation.
    Verified quiz outcomes: ``/api/v1/assessment-submit``.
    """
    hist = (
        [t.model_dump(exclude_none=True) for t in req.conversation_history]
        if req.conversation_history
        else None
    )
    result = generate_socratic_hint(
        user_id=req.user_id,
        topic_id=req.topic_id,
        student_answer=req.student_answer,
        conversation_history=hist,
        context_k=req.context_k,
        persona_id=req.persona_id,
    )
    if result.get("success"):
        score = result.get("interaction_score_effective")
        score_val = float(score) if isinstance(score, (int, float)) else None
        frustration_meta = _frustration_metadata_from_result(result)
        topic_used = str(result.get("topic_id") or req.topic_id)
        _record_tutor_turn(
            user_id=req.user_id,
            topic_id=topic_used,
            student_message=req.student_answer,
            tutor_message=str(result.get("hint_text") or ""),
            interaction_score=score_val,
            endpoint="/tutor/hint",
            persona_id=str(result.get("persona_id") or "") or None,
            hint_mode=str(result.get("hint_mode") or "") or None,
            topic_inferred=False,
            bkt_updated=bool(result.get("bkt_updated")),
            frustration_metadata=frustration_meta,
        )
        _append_interaction_log(
            user_id=req.user_id,
            topic_id=topic_used,
            interaction_score=score_val,
            endpoint="/tutor/hint",
            frustration_metadata=frustration_meta,
        )
        if isinstance(score, (int, float)) and topic_used:
            _append_signal(req.user_id, topic_used, float(score))
    return result


@app.post(
    "/tutor/hint-auto-topic",
    tags=["Tutor"],
    summary="Socratic hint (auto topic routing)",
    response_description="Same as /tutor/hint; topic may be inferred from student text",
)
def tutor_hint_auto_topic(req: TutorHintAutoTopicRequest) -> dict[str, Any]:
    """
    Question-only flow:
    if topic_id is absent, infer topic from question text.

    Same BKT rules as ``/tutor/hint``. Same response shape on success.
    """
    hist = (
        [t.model_dump(exclude_none=True) for t in req.conversation_history]
        if req.conversation_history
        else None
    )
    result = generate_socratic_hint_auto_topic(
        user_id=req.user_id,
        student_answer=req.student_answer,
        topic_id=req.topic_id,
        conversation_history=hist,
        context_k=req.context_k,
        persona_id=req.persona_id,
    )
    if result.get("success"):
        score = result.get("interaction_score_effective")
        score_val = float(score) if isinstance(score, (int, float)) else None
        resolved_topic = str(result.get("topic_id_resolved") or result.get("topic_id") or req.topic_id or "")
        frustration_meta = _frustration_metadata_from_result(result)
        topic_inferred = not bool(req.topic_id and str(req.topic_id).strip())
        _record_tutor_turn(
            user_id=req.user_id,
            topic_id=resolved_topic,
            student_message=req.student_answer,
            tutor_message=str(result.get("hint_text") or ""),
            interaction_score=score_val,
            endpoint="/tutor/hint-auto-topic",
            persona_id=str(result.get("persona_id") or "") or None,
            hint_mode=str(result.get("hint_mode") or "") or None,
            topic_inferred=topic_inferred,
            bkt_updated=bool(result.get("bkt_updated")),
            frustration_metadata=frustration_meta,
        )
        _append_interaction_log(
            user_id=req.user_id,
            topic_id=resolved_topic,
            interaction_score=score_val,
            endpoint="/tutor/hint-auto-topic",
            frustration_metadata=frustration_meta,
        )
        if isinstance(score, (int, float)) and resolved_topic:
            _append_signal(req.user_id, resolved_topic, float(score))
    return result


@app.post(
    "/api/v1/assessment-submit",
    tags=["Mastery"],
    summary="Record scored quiz attempt (Question Engine)",
    response_description="Updated P(L), Postgres assessment_attempts + bkt_mastery rows",
)
def assessment_submit(req: AssessmentSubmitRequest) -> dict[str, Any]:
    """
    Record a **ground-truth** correct/incorrect outcome from the question engine.

    Calls ``predict_update`` on the shared ``ScienceBKT`` so quiz results and
    tutor dialogue update the **same** per-learner, per-skill mastery.

    BKT uses only ``is_correct`` (and optional ``response_time_s``). ``question_type``
    (MCQ / ShortAnswer / MultiBlank / TrueFalse) is stored for analytics and does
    **not** change whether mastery is updated.

    After the BKT update, the attempt is inserted into Postgres
    ``learner_analytics.assessment_attempts`` when ``DATABASE_URL`` is set in ``.env``.
    """
    engine = get_shared_bkt_engine()
    label = 1 if req.is_correct else 0
    topic_id = str(req.topic_id)
    try:
        from curriculum_topics import normalize_topic_id

        topic_id = normalize_topic_id(topic_id)
    except Exception:
        pass
    response_time_s = float(req.response_time_s) if req.response_time_s is not None else None
    try:
        bkt_out = engine.predict_update(req.user_id, topic_id, label, response_time_s)
    except ValueError as exc:
        return {
            "success": False,
            "user_id": req.user_id,
            "topic_id": req.topic_id,
            "error": str(exc),
        }
    mastery = float(engine.get_current_mastery_probability(req.user_id, topic_id))
    category_fields = _mastery_category_payload(mastery)
    _append_signal(req.user_id, topic_id, float(label))
    attempt_record = _record_assessment_attempt(
        {
            "user_id": str(req.user_id),
            "topic_id": str(topic_id),
            "is_correct": bool(req.is_correct),
            "label": int(label),
            "question_type": req.question_type,
            "distractor_tag": req.distractor_tag,
            "distractor_label": req.distractor_label,
            "similarity_score": req.similarity_score,
            "error_category": req.error_category,
            "detailed_explanation": req.detailed_explanation,
            "missed_blanks": req.missed_blanks,
            "response_time_s": response_time_s,
            "difficulty_level": req.difficulty_level,
            "subtopic_id": req.subtopic_id,
            "question_id": req.question_id,
            "chosen_distractor_text": req.chosen_distractor_text,
            "source": req.source,
            "updated_mastery_probability": mastery,
            "mastery_category": category_fields["mastery_category"],
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    _persist_event("assessment_submit", attempt_record)
    postgres_result = insert_assessment_attempt(attempt_record)
    return {
        "success": True,
        "user_id": req.user_id,
        "topic_id": topic_id,
        "is_correct": bool(req.is_correct),
        "updated_mastery_probability": mastery,
        "mastery_probability": mastery,
        **category_fields,
        "risk_flag": bool(bkt_out.get("at_risk")),
        "bkt_observation_label": label,
        "label_source": "assessment",
        "postgres": postgres_result,
        "postgres_mastery": bkt_out.get("postgres_mastery"),
        "bkt_params_source": bkt_out.get("params_source"),
        "assessment_fields_persisted": {
            key: attempt_record.get(key)
            for key in (
                "question_type",
                "distractor_tag",
                "distractor_label",
                "similarity_score",
                "error_category",
                "detailed_explanation",
                "missed_blanks",
                "response_time_s",
                "difficulty_level",
                "subtopic_id",
                "question_id",
                "chosen_distractor_text",
                "source",
            )
            if attempt_record.get(key) is not None
        },
    }


@app.post(
    "/api/v1/engagement/frustration-cue",
    tags=["Engagement"],
    summary="Record frustration cue (Component 3)",
    response_description="Persisted to learner_analytics.frustration_cues; affects next tutor tone",
)
def engagement_frustration_cue(req: FrustrationCueSubmitRequest) -> dict[str, Any]:
    """
    Record an engagement/frustration signal for sentiment-aware tutoring.

    This does not directly update BKT mastery. Instead, the next tutor response for
    this ``(user_id, topic_id)`` consumes the latest cue to adapt tone/pacing.
    """
    signal = upsert_frustration_signal(
        user_id=req.user_id,
        topic_id=req.topic_id,
        frustration_score=req.frustration_score,
        source=req.source,
    )
    _frustration_history[(str(req.user_id), str(req.topic_id))].append(float(signal.frustration_score))
    cue_record = {
        "user_id": str(req.user_id),
        "topic_id": str(req.topic_id),
        "frustration_score": float(signal.frustration_score),
        "source": str(signal.source),
        "recorded_at": signal.recorded_at.isoformat(),
    }
    _persist_event("frustration_cue", cue_record)
    postgres_cue = insert_frustration_cue(cue_record)
    return {
        "success": True,
        "user_id": req.user_id,
        "topic_id": req.topic_id,
        "frustration_score": signal.frustration_score,
        "frustration_level": signal.level,
        "source": signal.source,
        "recorded_at": signal.recorded_at.isoformat(),
        "decay_tau_seconds": 600,
        "effective_floor": 0.2,
        "used_by": ["/tutor/hint", "/tutor/hint-auto-topic"],
        "postgres": postgres_cue,
    }


@app.get(
    "/api/v1/mastery/{user_id}/{topic_id}",
    tags=["Mastery"],
    summary="Get current BKT mastery + learner category (no new attempt)",
    response_description="Current P(L) and mastery_category for this student × topic",
)
def get_current_mastery(
    user_id: str = ApiPath(
        ...,
        description="Learner ID (same `user_id` used on assessment-submit and the tutor).",
        example="student_001",
    ),
    topic_id: str = ApiPath(
        ...,
        description=(
            "Canonical skill ID from Skill-Heirarchies-G6-G9-Full-Chapters.xlsx, "
            "e.g. G6_C8_ELE_CONDINS."
        ),
        example="G6_C8_ELE_CONDINS",
    ),
) -> dict[str, Any]:
    """
    **Read-only** current mastery for one learner on one topic.

    Use this when Question Engine or Content Generation needs:
    - `mastery_probability` — BKT P(L) in [0, 1]
    - `mastery_category` — `basic` | `intermediate` | `advanced`

    Thresholds: basic &lt; 0.50, intermediate 0.50–0.79, advanced ≥ 0.80.

    This does **not** record a quiz attempt. To *update* mastery after a scored
    question, call `POST /api/v1/assessment-submit` instead.
    """
    try:
        from curriculum_topics import normalize_topic_id

        topic_id = normalize_topic_id(topic_id)
    except Exception:
        pass
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    if topic_id not in engine.skill_map:
        return {
            "success": False,
            "user_id": user_id,
            "topic_id": topic_id,
            "error": f"Unknown topic_id: {topic_id}",
        }
    mastery = float(engine.get_current_mastery_probability(str(user_id), topic_id))
    state = engine.student_state.get((str(user_id), str(topic_id)), {})
    return {
        "success": True,
        "user_id": str(user_id),
        "topic_id": topic_id,
        "mastery_probability": mastery,
        **_mastery_category_payload(mastery),
        "attempts": int(state.get("attempts", 0)),
        "consecutive_incorrect": int(state.get("consecutive_incorrect", 0)),
        "hint_mode": (
            "scaffold"
            if mastery < _MASTERY_BASIC_MAX
            else ("nudge" if mastery >= _MASTERY_ADVANCED_MIN else "balanced")
        ),
    }


def _compute_mastery_from_live_state(student_ids: list[str], topic_ids: list[str]) -> dict[str, dict[str, float]]:
    """
    Build mastery matrix from shared in-memory engine + Postgres-backed BKT state.

    Unseen learner-topic pairs resolve to topic priors via get_current_mastery_probability.
    """
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    for sid in student_ids:
        engine.prefetch_learner_states(str(sid))
    known_topics = set(engine.skill_map.keys()) if engine.skill_map else set()
    matrix: dict[str, dict[str, float]] = {}
    for sid in student_ids:
        matrix[sid] = {}
        for tid in topic_ids:
            if known_topics and tid not in known_topics:
                matrix[sid][tid] = None
                continue
            matrix[sid][tid] = float(engine.get_current_mastery_probability(sid, tid))
    return matrix


def _select_current_topic_for_user(
    user_id: str,
    topics: list[str],
    engine: ScienceBKT,
) -> Optional[str]:
    """
    Pick a user's current topic for risk checks.

    Priority:
    1) Latest event topic seen via tutor/assessment ingestion.
    2) Topic with highest attempts in current in-memory BKT state.
    3) First topic from provided topic list.
    """
    uid = str(user_id)
    latest = _latest_topic_by_user.get(uid)
    if latest and latest in topics:
        return latest

    best_topic: Optional[str] = None
    best_attempts = -1
    for topic in topics:
        state = engine.student_state.get((uid, topic))
        if not isinstance(state, dict):
            continue
        attempts = int(state.get("attempts", 0))
        if attempts > best_attempts:
            best_attempts = attempts
            best_topic = topic
    if best_topic:
        return best_topic
    return topics[0] if topics else None


@app.post("/api/v1/analytics/at-risk-students", tags=["Analytics"])
def analytics_at_risk_students(req: Optional[AtRiskStudentsRequest] = None) -> dict[str, Any]:
    """
    Return students predicted as at-risk for intervention from live BKT + runtime signals.

    Criteria (current topic):
    - Low Mastery: P(L) < 0.45
    - Negative Velocity: last 3 tutor/assessment signals strictly decrease
    - Weak Recent Performance: recent signal average < 0.4
    """
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    all_topics = sorted(engine.skill_map.keys())
    topic_pool = [t for t in (req.topic_ids if req and req.topic_ids else all_topics) if t in engine.skill_map]
    known_users = _known_learner_ids(req.student_ids if req else None)

    alerts = []
    for uid in known_users:
        engine.prefetch_learner_states(uid)
        current_topic = _select_current_topic_for_user(uid, topic_pool, engine)
        if not current_topic:
            continue

        mastery = float(engine.get_current_mastery_probability(uid, current_topic))
        low_mastery = mastery < _MASTERY_LOW_THRESHOLD
        neg_velocity = _has_negative_velocity(uid, current_topic)
        recent_avg = _recent_signal_avg(uid, current_topic, window=5)
        weak_recent_perf = (recent_avg is not None) and (recent_avg < 0.4)

        alert = _compose_topic_risk_alert(
            student_id=uid,
            topic_id=current_topic,
            mastery=mastery,
            low_mastery=low_mastery,
            neg_velocity=neg_velocity,
            weak_recent_perf=weak_recent_perf,
            recent_signal_tail=list(_signal_history.get((uid, current_topic), []))[-3:],
            recent_performance_avg=recent_avg,
        )
        if alert:
            alerts.append(alert)

    alerts.sort(key=lambda a: a["risk_score"], reverse=True)
    return {
        "success": True,
        "mode": "live_state",
        "criteria": _risk_criteria_payload(),
        "count": len(alerts),
        "students": alerts,
    }


@app.get(
    "/api/v1/analytics/student-focus-areas/{user_id}",
    tags=["Analytics"],
    summary="Student focus areas (at-risk topics for one learner)",
    response_description="Topics this student should practice, ranked by risk_score",
)
def analytics_student_focus_areas(
    user_id: str = ApiPath(
        ...,
        description="Learner ID — same `user_id` used on tutor / assessment-submit.",
        example="user_001",
    ),
) -> dict[str, Any]:
    """
    **Student-facing** list of at-risk / focus topics for one learner.

    Scans every topic the learner has live evidence on (attempts, tutor signals, BKT state).
    Same risk rule as teacher alerts: at least 2 of
    low mastery / declining velocity / weak recent performance.
    """
    focus_areas, meta = _build_student_focus_areas(str(user_id))
    return {
        "success": True,
        "mode": "live_state",
        "user_id": str(user_id),
        "criteria": _risk_criteria_payload(),
        "count": len(focus_areas),
        "focus_areas": focus_areas,
        "meta": {
            "topics_scanned": meta.get("topics_scanned", 0),
            "audience": "student",
            "note": (
                "Empty focus_areas means no topic currently meets the at-risk rule "
                "for this learner."
            ),
        },
    }


@app.post("/api/v1/mastery/matrix", tags=["Analytics"])
def mastery_matrix(req: MasteryMatrixRequest) -> dict[str, Any]:
    """
    Return mastery probabilities for a classroom slice (students × topics).

    Uses live BKT state (in-memory + Postgres ``bkt_mastery``). Unseen pairs show skill priors.
    """
    matrix = _compute_mastery_from_live_state(req.student_ids, req.topic_ids)
    shared = get_shared_bkt_engine()
    known_topics = set(shared.skill_map.keys()) if shared.skill_map else set()
    unknown_topic_ids = [t for t in req.topic_ids if t not in known_topics]
    return {
        "success": True,
        "mode": "live_state",
        "student_ids": req.student_ids,
        "topic_ids": req.topic_ids,
        "unknown_topic_ids": unknown_topic_ids,
        "mastery_matrix": matrix,
    }


@app.get(
    "/api/v1/analytics/student-profile/{user_id}",
    tags=["Analytics"],
    summary="Deep-dive learner profile (teacher or student)",
)
def analytics_student_profile(user_id: str) -> dict[str, Any]:
    """
    Deep-dive profile for one learner from live BKT state, Postgres, and runtime events.

    Also embeds ``focus_areas`` (same payload as
    ``GET /api/v1/analytics/student-focus-areas/{user_id}``) for one-call profile pages.
    """
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    engine.prefetch_learner_states(str(user_id))

    live_attempts = _live_attempts_for_user(user_id)
    live_distractor_counts = _live_distractor_counts(user_id)
    distractor_counts = live_distractor_counts
    distractor_source = "question_engine_live" if live_distractor_counts else "none"

    topic_ids_for_bkt = sorted(
        {
            str(row.get("topic_id") or "")
            for row in live_attempts
            if row.get("topic_id")
        }
        | {
            tid
            for (u, tid), state in engine.student_state.items()
            if u == str(user_id)
            and isinstance(state, dict)
            and int(state.get("attempts", 0)) > 0
        }
        | {
            tid
            for (u, tid), vals in _signal_history.items()
            if u == str(user_id) and vals
        }
    )

    bkt_parameters: list[dict[str, Any]] = []
    for topic_id in topic_ids_for_bkt:
        params = engine.get_skill_parameters(topic_id)
        p_l = float(engine.get_current_mastery_probability(str(user_id), topic_id))
        bkt_parameters.append(
            {
                "topic_id": topic_id,
                "p_l": p_l,
                "mastery_category": _mastery_category_from_pl(p_l),
                "p_g": float(params.get("guess", 0.0)),
                "p_s": float(params.get("slip", 0.0)),
            }
        )

    topic_time_trends: list[dict[str, Any]] = []
    by_topic: dict[str, list[float]] = defaultdict(list)
    for row in live_attempts:
        topic = str(row.get("topic_id") or "")
        rt = row.get("response_time_s")
        if topic and isinstance(rt, (int, float)):
            by_topic[topic].append(float(rt))
    for topic_id, vals in by_topic.items():
        tail = vals[-10:]
        if len(tail) >= 2:
            slope = (tail[-1] - tail[0]) / float(len(tail) - 1)
            trend = "increasing" if slope > 0.15 else ("decreasing" if slope < -0.15 else "stable")
        else:
            trend = "stable"
        topic_time_trends.append(
            {
                "topic_id": topic_id,
                "avg_time_on_task_s": round(float(sum(tail) / len(tail)), 3) if tail else None,
                "last_10_time_on_task_s": [round(float(v), 3) for v in tail],
                "trend": trend,
            }
        )

    f_values = _load_frustration_values_for_user(str(user_id))
    avg_frustration = round(float(sum(f_values) / len(f_values)), 4) if f_values else None

    top_distractors = sorted(
        [{"tag": tag, "count": int(count)} for tag, count in distractor_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    engagement_tail = _load_tutor_turns_for_user(user_id, limit=10)
    chat_tail = [
        {
            "topic_id": row.get("topic_id"),
            "student_message": row.get("student_message"),
            "tutor_hint": row.get("tutor_hint"),
            "interaction_score": row.get("interaction_score"),
            "critical_confusion": row.get("critical_confusion"),
            "timestamp": row.get("timestamp"),
        }
        for row in engagement_tail[-5:]
    ]
    timeline_tail = [
        {
            "topic_id": str(row.get("topic_id") or ""),
            "is_correct": bool(row.get("is_correct")),
            "response_time_s": row.get("response_time_s"),
            "mastery_probability": row.get("updated_mastery_probability"),
            "distractor_label": row.get("distractor_label"),
            "question_type": row.get("question_type"),
            "error_category": row.get("error_category"),
            "detailed_explanation": row.get("detailed_explanation"),
            "missed_blanks": row.get("missed_blanks"),
            "similarity_score": row.get("similarity_score"),
        }
        for row in live_attempts[-10:]
    ]
    mastery_all = [
        float(row["updated_mastery_probability"])
        for row in live_attempts
        if isinstance(row.get("updated_mastery_probability"), (int, float))
    ]
    engagement_scores = [
        float(x.get("interaction_score"))
        for x in engagement_tail
        if isinstance(x.get("interaction_score"), (int, float))
    ]
    critical_confusion_turns = [
        row for row in chat_tail if bool(row.get("critical_confusion")) is True
    ]
    focus_areas, focus_meta = _build_student_focus_areas(str(user_id))
    topics_covered = len({str(r.get("topic_id")) for r in live_attempts if r.get("topic_id")})
    return {
        "success": True,
        "mode": "live_state",
        "user_id": str(user_id),
        "topics_covered_count": topics_covered,
        "bkt_parameters": bkt_parameters,
        "focus_areas": focus_areas,
        "focus_areas_count": len(focus_areas),
        "assessment_insights": {
            "most_frequent_distractor_tags": top_distractors,
            "attempts_count": len(live_attempts),
            "live_attempts_count": len(live_attempts),
        },
        "engagement_metrics": {
            "average_frustration_cue": avg_frustration,
            "frustration_samples": len(f_values),
            "time_on_task_trends": topic_time_trends,
        },
        "mastery_timeline_last_10_attempts": timeline_tail,
        "engagement_timeline_last_10_turns": engagement_tail,
        "engagement_average_last_10": (
            round(float(sum(engagement_scores) / len(engagement_scores)), 4)
            if engagement_scores
            else None
        ),
        "chat_history_last_5": chat_tail,
        "critical_confusion_turns": critical_confusion_turns,
        "meta": {
            "distractor_source": distractor_source,
            "mastery_timeline_points": len(timeline_tail),
            "engagement_points": len(engagement_tail),
            "chat_points": len(chat_tail),
            "engagement_source": "postgres" if postgres_configured() else "interaction_logs_json",
            "chat_source": "postgres" if postgres_configured() else "memory",
            "overall_mastery_tail": [round(v, 4) for v in mastery_all[-10:]],
            "focus_areas_topics_scanned": focus_meta.get("topics_scanned", 0),
            "focus_areas_endpoint": f"/api/v1/analytics/student-focus-areas/{user_id}",
        },
    }

