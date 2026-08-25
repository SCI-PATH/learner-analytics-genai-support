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
import threading
import time
from typing import Any, Literal, Optional

from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI, Path as ApiPath, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(_ENV_PATH, encoding="utf-8-sig")
_groq_from_file = str(dotenv_values(_ENV_PATH, encoding="utf-8-sig").get("GROQ_API_KEY") or "").strip()
if _groq_from_file and not os.environ.get("GROQ_API_KEY", "").strip():
    os.environ["GROQ_API_KEY"] = _groq_from_file

from bkt_engine import ScienceBKT
from postgres_store import (
    fetch_assessment_attempts_for_learner,
    fetch_assessment_attempts_for_learners,
    fetch_class_metadata,
    fetch_frustration_scores_for_learner,
    fetch_frustration_scores_for_learners,
    fetch_risk_signal_timeline,
    fetch_risk_signal_timelines_for_learners,
    fetch_roster_by_class_code,
    fetch_topic_ids_for_grade,
    fetch_tutor_turns_for_learner,
    fetch_tutor_turns_for_learners,
    insert_assessment_attempt,
    insert_frustration_cue,
    insert_tutor_turn,
    learner_in_class,
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
        "**Question Engine (quiz start):** `POST /api/v1/quiz/bkt-snapshot` returns current BKT "
        "P(L) + `mastery_category` for every topic in the requested chapter(s), without recording "
        "an attempt.\n\n"
        "**Question Engine / Content Gen (read one topic):** "
        "`GET /api/v1/mastery/{user_id}/{topic_id}` returns current BKT P(L) and "
        "`mastery_category` (`basic` / `intermediate` / `advanced`) without recording an attempt.\n\n"
        "**Question Engine (write attempt):** `POST /api/v1/assessment-submit` records a scored "
        "quiz item, updates BKT, and returns the new P(L) + category plus a `topic_bkt` map for "
        "the active chapter(s).\n\n"
        "**Student focus areas:** `GET /api/v1/analytics/student-focus-areas/{user_id}` lists "
        "at-risk topics for one learner (student profile).\n\n"
        "**Teacher Classroom Insights (fast path):** "
        "`GET /api/v1/analytics/classroom-dashboard?class_code=…` returns mastery matrix, "
        "at-risk feed, and class-summary in one pass.\n\n"
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
            "BKT mastery read/update. Question Engine starts a quiz with "
            "**POST /api/v1/quiz/bkt-snapshot**, writes scored attempts via "
            "**POST /api/v1/assessment-submit**, and can still read one topic with "
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
                "Teacher dashboard (matrix, at-risk, class-summary) and student "
                "profile / focus areas."
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
# Avoid re-reading Neon risk timelines on every matrix/at-risk/summary call.
_signal_rebuild_monotonic: dict[str, float] = {}
_SIGNAL_REBUILD_TTL_S = float(os.environ.get("ANALYTICS_SIGNAL_CACHE_TTL_S", "45") or 45)
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
_GUESS_HIGH_THRESHOLD = 0.20
_MASTERY_LOW_THRESHOLD = 0.45
_MASTERY_CRITICAL_THRESHOLD = 0.20
# Shared bands for tutor hint mode, dashboard heatmap, and teammate DDA.
_MASTERY_BASIC_MAX = 0.50
_MASTERY_ADVANCED_MIN = 0.80
# Research dashboard: high Socratic engagement vs low quiz mastery.
_ENGAGEMENT_GAP_ENGAGEMENT_MIN = 0.70
_ENGAGEMENT_GAP_MASTERY_MAX = 0.50
_FRUSTRATION_ELEVATED_THRESHOLD = 0.60


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
        "mastery_category_thresholds": _mastery_category_thresholds(),
    }


def _mastery_category_thresholds() -> dict[str, str]:
    return {
        "basic": f"P(L) < {_MASTERY_BASIC_MAX:.2f}",
        "intermediate": f"{_MASTERY_BASIC_MAX:.2f} <= P(L) < {_MASTERY_ADVANCED_MIN:.2f}",
        "advanced": f"P(L) >= {_MASTERY_ADVANCED_MIN:.2f}",
    }


def _topic_bkt_entry(engine: ScienceBKT, user_id: str, topic_id: str) -> dict[str, Any]:
    """Read-only per-topic BKT row for Question Engine session memory."""
    mastery = float(engine.get_current_mastery_probability(user_id, topic_id))
    state = engine.student_state.get((str(user_id), str(topic_id)), {})
    attempts = int(state.get("attempts", 0)) if isinstance(state, dict) else 0
    return {
        "mastery_probability": mastery,
        "mastery_category": _mastery_category_from_pl(mastery),
        "attempts": attempts,
        "seen": attempts > 0,
    }


def _build_quiz_bkt_snapshot(user_id: str, chapter_ids: list[str]) -> dict[str, Any]:
    """Chapter-scoped BKT map. Does not record a new attempt."""
    from curriculum_topics import resolve_chapter_scope

    scope = resolve_chapter_scope(chapter_ids)
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    engine.prefetch_learner_states(str(user_id))
    known_topics = set(engine.skill_map.keys()) if engine.skill_map else set()
    topic_bkt: dict[str, Any] = {}
    for tid in scope["topic_ids"]:
        if known_topics and tid not in known_topics:
            topic_bkt[tid] = None
            continue
        try:
            topic_bkt[tid] = _topic_bkt_entry(engine, str(user_id), tid)
        except ValueError:
            topic_bkt[tid] = None
    return {
        "chapter_ids": scope["chapter_ids"],
        "unknown_chapter_ids": scope["unknown_chapter_ids"],
        "topic_ids": scope["topic_ids"],
        "topics_by_chapter": scope["topics_by_chapter"],
        "topic_bkt": topic_bkt,
        "mastery_category_thresholds": _mastery_category_thresholds(),
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


def _clear_runtime_buffers_for_learners(user_ids: list[str]) -> None:
    """Drop in-memory analytics buffers so a classroom seed can start from priors."""
    ids = {str(uid) for uid in user_ids if str(uid).strip()}
    for key in [k for k in list(_signal_history.keys()) if str(k[0]) in ids]:
        del _signal_history[key]
    for key in [k for k in list(_frustration_history.keys()) if str(k[0]) in ids]:
        del _frustration_history[key]
    for uid in ids:
        _latest_topic_by_user.pop(uid, None)
        _chat_history_by_user.pop(uid, None)
        _assessment_attempts_by_user.pop(uid, None)
        _signal_rebuild_monotonic.pop(uid, None)


def _apply_signal_timeline(user_id: str, timeline: list[tuple[str, float]]) -> None:
    """Replace one learner's in-memory risk signals from a prepared timeline."""
    uid = str(user_id)
    for key in [k for k in list(_signal_history.keys()) if str(k[0]) == uid]:
        del _signal_history[key]
    _latest_topic_by_user.pop(uid, None)
    for topic_id, value in timeline:
        _append_signal(uid, topic_id, float(value))
    _signal_rebuild_monotonic[uid] = time.monotonic()


def _rebuild_signals_from_postgres(user_id: str, *, force: bool = False) -> None:
    """Replace in-memory risk signals from persisted attempts + tutor scores."""
    if not postgres_configured():
        return
    uid = str(user_id)
    now = time.monotonic()
    last = _signal_rebuild_monotonic.get(uid)
    if (
        not force
        and last is not None
        and (now - last) < _SIGNAL_REBUILD_TTL_S
        and any(k[0] == uid for k in _signal_history)
    ):
        return
    timeline = fetch_risk_signal_timeline(uid)
    _apply_signal_timeline(uid, timeline)


def _rebuild_signals_for_learners(user_ids: list[str], *, force: bool = False) -> None:
    """Batch-rebuild risk signals for a classroom roster (one Neon round-trip pair)."""
    if not postgres_configured():
        return
    ids = [str(uid) for uid in user_ids if str(uid).strip()]
    if not ids:
        return
    now = time.monotonic()
    stale = [
        uid
        for uid in ids
        if force
        or uid not in _signal_rebuild_monotonic
        or (now - _signal_rebuild_monotonic[uid]) >= _SIGNAL_REBUILD_TTL_S
        or not any(k[0] == uid for k in _signal_history)
    ]
    if not stale:
        return
    timelines = fetch_risk_signal_timelines_for_learners(stale)
    for uid in stale:
        _apply_signal_timeline(uid, timelines.get(uid, []))


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
    try:
        if postgres_configured():
            # Postgres is the source of truth; risk signals are rebuilt per learner
            # on analytics reads. Replaying sqlite here re-upserts every frustration
            # cue into Neon and blocks uvicorn startup.
            return
    except Exception:
        pass
    events = _load_persisted_events()
    if not events:
        return
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
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
        "watchlist_override_rule": (
            "weak_recent_and_negative_velocity_without_low_mastery_scores_55"
        ),
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
    elif neg_velocity and weak_recent_perf and not low_mastery:
        # Trend risk while P(L) is still above the low-mastery cut → Watchlist (40–59).
        risk_score = 55

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
    _rebuild_signals_from_postgres(uid)

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


_ERROR_CATEGORY_TAGS = {"NEAR_MISS", "MISCONCEPTION", "COMPLETE_MISS"}


def _misconception_cloud_label(attempt: dict[str, Any]) -> Optional[str]:
    """Phrase for the misconception cloud — never the error-category tag itself.

    NEAR_MISS / COMPLETE_MISS / MISCONCEPTION describe *how* the miss happened.
    Teachers need the actual wrong idea (e.g. "Current is used up in the bulb").
    """
    if bool(attempt.get("is_correct")):
        return None
    label = str(attempt.get("distractor_label") or "").strip()
    if label and label.upper().replace(" ", "_") not in _ERROR_CATEGORY_TAGS:
        return label
    chosen = str(attempt.get("chosen_distractor_text") or "").strip()
    if chosen:
        return chosen[:80] + ("..." if len(chosen) > 80 else "")
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
    chapter_ids: Optional[list[str]] = Field(
        None,
        description=(
            "Active quiz chapter keys from Data/chapter_ids_g6_g9.csv, "
            'e.g. ["G6_C8", "G6_C7"]. Format: G{grade}_C{chapter}. '
            "When omitted, the response `topic_bkt` map covers only the answered topic's chapter."
        ),
        examples=[["G6_C8"], ["G6_C8", "G6_C7"]],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "student_001",
                    "topic_id": "G6_C8_ELE_CIRCUITS",
                    "is_correct": True,
                    "question_type": "MCQ",
                    "source": "question_engine_v1",
                    "chapter_ids": ["G6_C8"],
                }
            ]
        }
    )

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


class QuizBktSnapshotRequest(BaseModel):
    """Read-only BKT snapshot for quiz initialization (no attempt recorded)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"user_id": "student_001", "chapter_ids": ["G6_C8"]},
                {"user_id": "student_001", "chapter_ids": ["G6_C8", "G6_C7"]},
            ]
        }
    )

    user_id: str = Field(..., description="Student identifier (same ID used on assessment-submit)")
    chapter_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Chapter keys from Data/chapter_ids_g6_g9.csv. "
            "Format G{grade}_C{chapter}, e.g. G6_C8. "
            "Post-lesson: one id. Custom exam: every selected chapter."
        ),
        examples=[["G6_C8"], ["G6_C8", "G6_C7"]],
    )


class FrustrationCueSubmitRequest(BaseModel):
    """Engagement module cue for sentiment-aware tutor tone adaptation."""

    user_id: str = Field(..., description="Student identifier")
    topic_id: str = Field(..., description="Curriculum topic / skill id")
    frustration_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description=(
            "Frustration intensity. Prefer 0.0–1.0. Values above 1.0 (up to 100) "
            "are treated as a 0–100 score and divided by 100."
        ),
    )
    source: str = Field(
        "engagement_module",
        description="Producer identifier (e.g., engagement_module_v1)",
    )

    @field_validator("frustration_score")
    @classmethod
    def _normalize_frustration_score(cls, value: float) -> float:
        score = float(value)
        if score > 1.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))


class MasteryMatrixRequest(BaseModel):
    """Request payload for classroom mastery matrix (live BKT + Postgres state)."""

    class_code: Optional[str] = Field(
        None,
        description=(
            "When set, roster and grade-scoped topics are resolved from "
            "``shared.classes`` / ``shared.class_enrollments`` / ``shared.topics``."
        ),
        examples=["SCI-G7-492"],
    )
    student_ids: Optional[list[str]] = Field(
        None,
        min_length=1,
        description="Manual roster slice (ignored when ``class_code`` is provided).",
    )
    topic_ids: Optional[list[str]] = Field(
        None,
        min_length=1,
        description="Manual topic columns (ignored when ``class_code`` is provided).",
    )

    @model_validator(mode="after")
    def _validate_scope(self) -> "MasteryMatrixRequest":
        code = (self.class_code or "").strip()
        if code:
            return self
        if not self.student_ids or not self.topic_ids:
            raise ValueError("Provide class_code or both student_ids and topic_ids.")
        return self


class AtRiskStudentsRequest(BaseModel):
    """Optional filter controls for at-risk analytics."""

    class_code: Optional[str] = Field(
        None,
        description=(
            "When set, roster and grade-scoped topics are resolved from the shared schema."
        ),
        examples=["SCI-G7-492"],
    )
    student_ids: Optional[list[str]] = Field(None, description="Restrict scan to these students")
    topic_ids: Optional[list[str]] = Field(None, description="Restrict scan to these topics")


_SEED_RUNTIME_TOKENS = {
    "seed_g8_class_dashboard",
    "seed_g8_student_deepdive",
}


class ResetLearnerRuntimeRequest(BaseModel):
    """Clear in-memory BKT / signal buffers so a classroom seed can start from priors."""

    learner_ids: list[str] = Field(..., min_length=1)
    confirm: str = Field(
        ...,
        description="Must match a seed source token (seed_g8_class_dashboard or seed_g8_student_deepdive).",
    )
    skill_ids: Optional[list[str]] = Field(
        None,
        description="Optional topic IDs whose cached BKT params should reload from Postgres.",
    )


def _topic_ids_for_grade_level(grade_level: int, engine: ScienceBKT) -> list[str]:
    """Grade-scoped topic columns: ``shared.topics`` first, then BKT skill-map prefix."""
    topic_ids = fetch_topic_ids_for_grade(grade_level)
    if topic_ids:
        if engine.skill_map:
            known = set(engine.skill_map.keys())
            topic_ids = [tid for tid in topic_ids if tid in known]
        return topic_ids
    prefix = f"G{int(grade_level)}_"
    if engine.skill_map:
        return sorted(t for t in engine.skill_map if str(t).upper().startswith(prefix))
    return []


def _resolve_class_scope(class_code: str, engine: ScienceBKT) -> dict[str, Any]:
    """Resolve roster + grade topic columns for one classroom."""
    code = str(class_code or "").strip().upper()
    if not code:
        return {"success": False, "error": "class_code is required."}
    if not postgres_configured():
        return {
            "success": False,
            "error": (
                "DATABASE_URL is not configured. Class scoping requires Postgres "
                "access to shared.classes / shared.class_enrollments."
            ),
        }
    meta = fetch_class_metadata(code)
    if not meta:
        return {"success": False, "error": f"Unknown class_code: {code}"}
    if not meta.get("is_active", True):
        return {"success": False, "error": f"Class is inactive: {code}"}
    student_ids = fetch_roster_by_class_code(code)
    topic_ids = _topic_ids_for_grade_level(int(meta["grade_level"]), engine)
    return {
        "success": True,
        "class_code": meta["class_code"],
        "class_name": meta["class_name"],
        "grade_level": int(meta["grade_level"]),
        "subject": meta.get("subject"),
        "teacher_id": meta.get("teacher_id"),
        "student_ids": student_ids,
        "topic_ids": topic_ids,
    }


def _resolve_analytics_scope(
    req: Optional[MasteryMatrixRequest | AtRiskStudentsRequest],
    engine: ScienceBKT,
) -> dict[str, Any]:
    """Merge explicit filters with optional ``class_code`` classroom scope."""
    class_code = (getattr(req, "class_code", None) or "").strip() if req else ""
    if class_code:
        scope = _resolve_class_scope(class_code, engine)
        if not scope.get("success"):
            return scope
        student_ids = list(scope["student_ids"])
        topic_ids = list(scope["topic_ids"])
        if req and req.topic_ids:
            allowed = set(req.topic_ids)
            topic_ids = [t for t in topic_ids if t in allowed]
        scope["student_ids"] = student_ids
        scope["topic_ids"] = topic_ids
        return scope

    all_topics = sorted(engine.skill_map.keys()) if engine.skill_map else []
    student_ids = list(req.student_ids) if req and req.student_ids else _known_learner_ids(None)
    topic_ids = (
        [t for t in req.topic_ids if t in engine.skill_map]
        if req and req.topic_ids
        else all_topics
    )
    return {
        "success": True,
        "student_ids": student_ids,
        "topic_ids": topic_ids,
    }


@app.get("/health", tags=["Health"], summary="Health check")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def _startup_init() -> None:
    _init_persistence()
    _hydrate_live_state_from_db()
    # Warm BKT/RAG off the request thread so /health and classroom seeding
    # are not blocked if Chroma or Postgres is slow after a --reload.
    threading.Thread(
        target=_warmup_heavy_dependencies,
        name="analytics-warmup",
        daemon=True,
    ).start()


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
    "/api/v1/quiz/bkt-snapshot",
    tags=["Mastery"],
    summary="Quiz init: BKT snapshot for chapter(s) (Question Engine)",
    response_description="Per-topic P(L) + mastery_category for all skills in the requested chapters",
)
def quiz_bkt_snapshot(req: QuizBktSnapshotRequest) -> dict[str, Any]:
    """
    **Read-only** chapter-scoped BKT snapshot for quiz initialization.

    Question Engine calls this **once before the first question** with the
    selected chapter key(s). Component 4 remains the source of truth: this
    does **not** record an attempt or change mastery.

    ``chapter_ids`` use the shared key ``G{grade}_C{chapter}`` (example: ``G6_C8``).
    Each chapter currently maps to two canonical ``topic_id`` skills.

    Unseen learner–topic pairs return the skill **prior** with ``seen: false``
    and ``attempts: 0`` — not ``null``.
    """
    snapshot = _build_quiz_bkt_snapshot(str(req.user_id), list(req.chapter_ids))
    if not snapshot["chapter_ids"]:
        return {
            "success": False,
            "user_id": str(req.user_id),
            "chapter_ids": [],
            "unknown_chapter_ids": snapshot["unknown_chapter_ids"],
            "topic_ids": [],
            "topics_by_chapter": {},
            "topic_bkt": {},
            "mastery_category_thresholds": snapshot["mastery_category_thresholds"],
            "error": (
                "No valid chapter_ids. Use G{grade}_C{chapter} keys from the shared "
                "curriculum, e.g. G6_C8."
            ),
        }
    return {
        "success": True,
        "user_id": str(req.user_id),
        **snapshot,
    }


@app.post(
    "/api/v1/assessment-submit",
    tags=["Mastery"],
    summary="Record scored quiz attempt (Question Engine)",
    response_description="Updated P(L) for the answered topic plus topic_bkt for active chapters",
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

    The JSON response still includes the answered topic's P(L) and category.
    It also includes ``topic_bkt`` for the active quiz chapters so Question Engine
    can refresh session memory. Pass ``chapter_ids`` for multi-chapter exams;
    otherwise the map covers only the answered topic's chapter.
    """
    engine = get_shared_bkt_engine()
    label = 1 if req.is_correct else 0
    topic_id = str(req.topic_id)
    from curriculum_topics import chapter_id_for_topic, normalize_topic_id

    topic_id = normalize_topic_id(topic_id)
    response_time_s = float(req.response_time_s) if req.response_time_s is not None else None
    try:
        bkt_out = engine.predict_update(req.user_id, topic_id, label, response_time_s)
    except ValueError as except_exc:
        return {
            "success": False,
            "user_id": req.user_id,
            "topic_id": req.topic_id,
            "error": str(except_exc),
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

    active_chapters = [str(cid) for cid in (req.chapter_ids or []) if str(cid).strip()]
    if not active_chapters:
        inferred = chapter_id_for_topic(topic_id)
        if inferred:
            active_chapters = [inferred]
    snapshot = (
        _build_quiz_bkt_snapshot(str(req.user_id), active_chapters) if active_chapters else {
            "chapter_ids": [],
            "unknown_chapter_ids": [],
            "topic_ids": [],
            "topics_by_chapter": {},
            "topic_bkt": {},
        }
    )

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
        "chapter_ids": snapshot["chapter_ids"],
        "unknown_chapter_ids": snapshot["unknown_chapter_ids"],
        "topic_ids": snapshot["topic_ids"],
        "topics_by_chapter": snapshot["topics_by_chapter"],
        "topic_bkt": snapshot["topic_bkt"],
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


def _mean_or_none(values: list[float], *, digits: int = 4) -> Optional[float]:
    if not values:
        return None
    return round(float(sum(values) / len(values)), digits)


def _mastery_values_from_attempts(attempts: list[dict[str, Any]], *, limit: int = 10) -> list[float]:
    values: list[float] = []
    for row in attempts[-max(1, int(limit)) :]:
        raw = row.get("updated_mastery_probability")
        if raw is None:
            raw = row.get("mastery_probability")
        if isinstance(raw, (int, float)):
            values.append(float(raw))
    return values


def _engagement_values_from_turns(turns: list[dict[str, Any]]) -> list[float]:
    return [
        float(row.get("interaction_score"))
        for row in turns
        if isinstance(row.get("interaction_score"), (int, float))
    ]


def _engagement_mastery_gap_payload(
    engagement_average: Optional[float],
    mastery_average: Optional[float],
) -> dict[str, Any]:
    """Flag learners who participate in tutoring but struggle on formal assessment."""
    flagged = (
        engagement_average is not None
        and mastery_average is not None
        and float(engagement_average) >= _ENGAGEMENT_GAP_ENGAGEMENT_MIN
        and float(mastery_average) < _ENGAGEMENT_GAP_MASTERY_MAX
    )
    return {
        "flagged": bool(flagged),
        "engagement_average": engagement_average,
        "mastery_average": mastery_average,
        "thresholds": {
            "engagement_min": _ENGAGEMENT_GAP_ENGAGEMENT_MIN,
            "mastery_max": _ENGAGEMENT_GAP_MASTERY_MAX,
        },
    }


def _build_diagnostic_skills(bkt_parameters: list[dict[str, Any]]) -> dict[str, Any]:
    """Skills this learner has evidence on where the BKT model is high-slip or high-guess."""
    high_slip: list[dict[str, Any]] = []
    high_guess: list[dict[str, Any]] = []
    for row in bkt_parameters:
        topic_id = str(row.get("topic_id") or "")
        if not topic_id:
            continue
        p_s = float(row.get("p_s") or 0.0)
        p_g = float(row.get("p_g") or 0.0)
        item = {
            "topic_id": topic_id,
            "p_l": row.get("p_l"),
            "mastery_category": row.get("mastery_category"),
            "p_s": round(p_s, 4),
            "p_g": round(p_g, 4),
        }
        if p_s > _SLIP_HIGH_THRESHOLD:
            high_slip.append({**item, "flag": "high_slip"})
        if p_g > _GUESS_HIGH_THRESHOLD:
            high_guess.append({**item, "flag": "high_guess"})
    high_slip.sort(key=lambda x: float(x.get("p_s") or 0.0), reverse=True)
    high_guess.sort(key=lambda x: float(x.get("p_g") or 0.0), reverse=True)
    flagged_ids = {str(r["topic_id"]) for r in high_slip} | {str(r["topic_id"]) for r in high_guess}
    return {
        "high_slip": high_slip,
        "high_guess": high_guess,
        "count": len(flagged_ids),
        "thresholds": {
            "p_s": _SLIP_HIGH_THRESHOLD,
            "p_g": _GUESS_HIGH_THRESHOLD,
        },
        "interpretation": {
            "high_slip": (
                "Incorrect answers on these skills may be slips (the model is noisy) "
                "rather than lack of knowledge."
            ),
            "high_guess": (
                "Correct answers on these skills may include lucky guesses; "
                "treat a high P(L) with caution."
            ),
        },
    }


def _privacy_safe_recent_attempts(
    attempts: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Table-ready attempt rows for teachers — no free-text explanations."""
    rows: list[dict[str, Any]] = []
    for row in attempts[-max(1, int(limit)) :]:
        rows.append(
            {
                "topic_id": str(row.get("topic_id") or ""),
                "is_correct": bool(row.get("is_correct")),
                "response_time_s": row.get("response_time_s"),
                "mastery_probability": row.get("updated_mastery_probability", row.get("mastery_probability")),
                "distractor_label": row.get("distractor_label"),
                "question_type": row.get("question_type"),
                "error_category": row.get("error_category"),
                "timestamp": row.get("timestamp"),
            }
        )
    return rows


def _distractor_counts_from_attempts(attempts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for attempt in attempts:
        cloud_label = _misconception_cloud_label(attempt)
        if cloud_label:
            counts[cloud_label] += 1
    return dict(counts)


def _mastery_band_counts_from_matrix(
    matrix: dict[str, dict[str, float]],
    student_ids: list[str],
    topic_ids: list[str],
) -> dict[str, Any]:
    mastered = 0
    learning = 0
    at_risk = 0
    for sid in student_ids:
        row = matrix.get(sid) or {}
        for tid in topic_ids:
            value = row.get(tid)
            if not isinstance(value, (int, float)):
                continue
            category = _mastery_category_from_pl(float(value))
            if category == "advanced":
                mastered += 1
            elif category == "intermediate":
                learning += 1
            else:
                at_risk += 1
    return {
        "mastered": mastered,
        "learning": learning,
        "at_risk": at_risk,
        "total": len(student_ids) * len(topic_ids),
        "thresholds": {
            "mastered": f"P(L) >= {_MASTERY_ADVANCED_MIN:.2f}",
            "learning": f"{_MASTERY_BASIC_MAX:.2f} <= P(L) < {_MASTERY_ADVANCED_MIN:.2f}",
            "at_risk": f"P(L) < {_MASTERY_BASIC_MAX:.2f}",
        },
    }


def _hardest_skills_from_matrix(
    matrix: dict[str, dict[str, float]],
    student_ids: list[str],
    topic_ids: list[str],
    *,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    roster_n = len(student_ids)
    ranked: list[dict[str, Any]] = []
    for tid in topic_ids:
        values: list[float] = []
        at_risk_count = 0
        for sid in student_ids:
            value = (matrix.get(sid) or {}).get(tid)
            if not isinstance(value, (int, float)):
                continue
            values.append(float(value))
            if float(value) < _MASTERY_BASIC_MAX:
                at_risk_count += 1
        if not values:
            continue
        ranked.append(
            {
                "topic_id": tid,
                "avg_mastery": round(float(sum(values) / len(values)), 4),
                "at_risk_count": at_risk_count,
                "at_risk_share": round(at_risk_count / roster_n, 4) if roster_n else 0.0,
            }
        )
    ranked.sort(key=lambda row: (-float(row["at_risk_share"]), float(row["avg_mastery"])))
    return ranked[: max(1, int(top_n))]


def _top_at_risk_skills(alerts: list[dict[str, Any]], *, top_n: int = 5) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"alert_count": 0, "risk_sum": 0.0})
    for alert in alerts:
        topic_id = str(alert.get("topic_id") or "")
        if not topic_id:
            continue
        buckets[topic_id]["alert_count"] += 1
        buckets[topic_id]["risk_sum"] += float(alert.get("risk_score") or 0)
    ranked = [
        {
            "topic_id": topic_id,
            "alert_count": int(stats["alert_count"]),
            "avg_risk_score": round(float(stats["risk_sum"]) / float(stats["alert_count"]), 2),
        }
        for topic_id, stats in buckets.items()
    ]
    ranked.sort(key=lambda row: (-int(row["alert_count"]), -float(row["avg_risk_score"])))
    return ranked[: max(1, int(top_n))]


def _scan_current_topic_at_risk_alerts(
    known_users: list[str],
    topic_pool: list[str],
    engine: ScienceBKT,
) -> list[dict[str, Any]]:
    """Same 2-of-3 current-topic scan used by the classroom at-risk feed."""
    alerts: list[dict[str, Any]] = []
    _rebuild_signals_for_learners(known_users)
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
    return alerts


@app.post("/api/v1/analytics/at-risk-students", tags=["Analytics"])
def analytics_at_risk_students(req: Optional[AtRiskStudentsRequest] = None) -> dict[str, Any]:
    """
    Return students predicted as at-risk for intervention from live BKT + runtime signals.

    Criteria (current topic):
    - Low Mastery: P(L) < 0.45
    - Negative Velocity: last 3 tutor/assessment signals strictly decrease
    - Weak Recent Performance: recent signal average < 0.4

    When ``class_code`` is provided, only learners enrolled in that class are scanned and
    topics are limited to the class grade (``shared.topics`` or ``G{n}_*`` fallback).
    """
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    scope = _resolve_analytics_scope(req, engine)
    if not scope.get("success"):
        return {"success": False, "error": scope.get("error", "Invalid analytics scope.")}

    topic_pool = [t for t in scope["topic_ids"] if t in engine.skill_map]
    known_users = _known_learner_ids(scope["student_ids"])

    alerts = _scan_current_topic_at_risk_alerts(known_users, topic_pool, engine)
    payload: dict[str, Any] = {
        "success": True,
        "mode": "live_state",
        "criteria": _risk_criteria_payload(),
        "count": len(alerts),
        "students": alerts,
        "student_ids": scope["student_ids"],
        "topic_ids": topic_pool,
    }
    for key in ("class_code", "class_name", "grade_level", "subject", "teacher_id"):
        if key in scope:
            payload[key] = scope[key]
    return payload


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

    When ``class_code`` is provided, roster and grade-scoped topics are loaded from the
    shared schema (``shared.classes``, ``shared.class_enrollments``, ``shared.topics``).
    """
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    scope = _resolve_analytics_scope(req, engine)
    if not scope.get("success"):
        return {"success": False, "error": scope.get("error", "Invalid analytics scope.")}

    student_ids = list(scope["student_ids"])
    topic_ids = list(scope["topic_ids"])
    matrix = _compute_mastery_from_live_state(student_ids, topic_ids)
    known_topics = set(engine.skill_map.keys()) if engine.skill_map else set()
    unknown_topic_ids = [t for t in topic_ids if t not in known_topics]
    payload: dict[str, Any] = {
        "success": True,
        "mode": "live_state",
        "student_ids": student_ids,
        "topic_ids": topic_ids,
        "unknown_topic_ids": unknown_topic_ids,
        "mastery_matrix": matrix,
        "roster_count": len(student_ids),
        "topic_count": len(topic_ids),
    }
    for key in ("class_code", "class_name", "grade_level", "subject", "teacher_id"):
        if key in scope:
            payload[key] = scope[key]
    return payload


@app.get(
    "/api/v1/analytics/student-profile/{user_id}",
    tags=["Analytics"],
    summary="Deep-dive learner profile (teacher or student)",
)
def analytics_student_profile(
    user_id: str,
    class_code: Optional[str] = Query(
        None,
        description=(
            "When provided, returns 403-style error payload if the learner is not "
            "enrolled in this class (teacher dashboard scoping)."
        ),
    ),
) -> dict[str, Any]:
    """
    Deep-dive profile for one learner from live BKT state, Postgres, and runtime events.

    Also embeds ``focus_areas`` (same payload as
    ``GET /api/v1/analytics/student-focus-areas/{user_id}``) for one-call profile pages.

    Optional ``class_code`` restricts access to learners on that classroom roster.
    """
    code = (class_code or "").strip().upper()
    if code and not learner_in_class(str(user_id), code):
        return {
            "success": False,
            "user_id": str(user_id),
            "class_code": code,
            "error": f"Learner {user_id} is not enrolled in class {code}.",
        }
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
    engagement_average = (
        round(float(sum(engagement_scores) / len(engagement_scores)), 4)
        if engagement_scores
        else None
    )
    mastery_last_10 = _mastery_values_from_attempts(live_attempts, limit=10)
    diagnostic_skills = _build_diagnostic_skills(bkt_parameters)
    recent_attempts = _privacy_safe_recent_attempts(live_attempts, limit=10)
    engagement_mastery_gap = _engagement_mastery_gap_payload(
        engagement_average,
        _mean_or_none(mastery_last_10),
    )
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
        "recent_attempts": recent_attempts,
        "diagnostic_skills": diagnostic_skills,
        "engagement_mastery_gap": engagement_mastery_gap,
        "engagement_timeline_last_10_turns": engagement_tail,
        "engagement_average_last_10": engagement_average,
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
            "diagnostic_skills_count": diagnostic_skills.get("count", 0),
            "recent_attempts_count": len(recent_attempts),
            "engagement_mastery_gap_flagged": bool(engagement_mastery_gap.get("flagged")),
        },
    }


def _build_class_summary_payload(
    *,
    scope: dict[str, Any],
    engine: ScienceBKT,
    matrix: Optional[dict[str, dict[str, Any]]] = None,
    alerts: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Aggregate classroom research metrics from existing live-state helpers."""
    student_ids = list(scope.get("student_ids") or [])
    topic_ids = [t for t in (scope.get("topic_ids") or []) if t in engine.skill_map]
    if matrix is None:
        matrix = _compute_mastery_from_live_state(student_ids, topic_ids)
    known_users = _known_learner_ids(student_ids)
    if alerts is None:
        alerts = _scan_current_topic_at_risk_alerts(known_users, topic_ids, engine)

    attempts_by_user = (
        fetch_assessment_attempts_for_learners(student_ids, limit_per_learner=200)
        if postgres_configured()
        else {}
    )
    turns_by_user = (
        fetch_tutor_turns_for_learners(student_ids, limit_per_learner=10)
        if postgres_configured()
        else {}
    )
    frustration_by_user = (
        fetch_frustration_scores_for_learners(student_ids)
        if postgres_configured()
        else {}
    )

    gap_learners: list[dict[str, Any]] = []
    distractor_counts: dict[str, int] = defaultdict(int)
    distractor_learners: dict[str, set[str]] = defaultdict(set)
    frustration_all: list[float] = []
    elevated_frustration: list[str] = []
    learners_with_attempts = 0

    for uid in student_ids:
        attempts = attempts_by_user.get(uid) or _live_attempts_for_user(uid)
        if attempts:
            learners_with_attempts += 1
        for tag, count in _distractor_counts_from_attempts(attempts).items():
            distractor_counts[tag] += int(count)
            distractor_learners[tag].add(uid)

        turns = turns_by_user.get(uid) or _load_tutor_turns_for_user(uid, limit=10)
        engagement_avg = _mean_or_none(_engagement_values_from_turns(turns))
        mastery_avg = _mean_or_none(_mastery_values_from_attempts(attempts, limit=10))
        gap = _engagement_mastery_gap_payload(engagement_avg, mastery_avg)
        if gap["flagged"]:
            gap_learners.append(
                {
                    "student_id": uid,
                    "engagement_average": engagement_avg,
                    "mastery_average": mastery_avg,
                }
            )

        f_vals = frustration_by_user.get(uid) or _load_frustration_values_for_user(uid)
        if f_vals:
            frustration_all.extend(f_vals)
            learner_avg = float(sum(f_vals) / len(f_vals))
            if learner_avg > _FRUSTRATION_ELEVATED_THRESHOLD:
                elevated_frustration.append(uid)

    top_distractors = sorted(
        [
            {
                "tag": tag,
                "count": int(count),
                "learner_count": len(distractor_learners[tag]),
            }
            for tag, count in distractor_counts.items()
        ],
        key=lambda row: int(row["count"]),
        reverse=True,
    )[:5]

    payload: dict[str, Any] = {
        "success": True,
        "mode": "live_state",
        "roster_count": len(student_ids),
        "topic_count": len(topic_ids),
        "student_ids": student_ids,
        "topic_ids": topic_ids,
        "mastery_bands": _mastery_band_counts_from_matrix(matrix, student_ids, topic_ids),
        "hardest_skills": _hardest_skills_from_matrix(matrix, student_ids, topic_ids, top_n=5),
        "at_risk_feed": {
            "count": len(alerts),
            "top_skills": _top_at_risk_skills(alerts, top_n=5),
        },
        "top_distractors": top_distractors,
        "engagement_mastery_gap": {
            "count": len(gap_learners),
            "learners": gap_learners,
            "thresholds": {
                "engagement_min": _ENGAGEMENT_GAP_ENGAGEMENT_MIN,
                "mastery_max": _ENGAGEMENT_GAP_MASTERY_MAX,
            },
            "note": (
                "Learners with high Socratic dialogue engagement "
                f"(>= {_ENGAGEMENT_GAP_ENGAGEMENT_MIN:.0%}) but low recent "
                f"assessment mastery (< {_ENGAGEMENT_GAP_MASTERY_MAX:.0%})."
            ),
        },
        "frustration": {
            "class_average": _mean_or_none(frustration_all),
            "samples": len(frustration_all),
            "elevated_count": len(elevated_frustration),
            "elevated_learner_ids": elevated_frustration,
            "threshold": _FRUSTRATION_ELEVATED_THRESHOLD,
        },
        "meta": {
            "learners_with_attempts": learners_with_attempts,
            "known_learners_scanned_for_risk": len(known_users),
            "criteria": _risk_criteria_payload(),
            "batch_postgres": bool(postgres_configured()),
        },
    }
    for key in ("class_code", "class_name", "grade_level", "subject", "teacher_id"):
        if key in scope:
            payload[key] = scope[key]
    return payload


def _build_classroom_dashboard_payload(
    *,
    scope: dict[str, Any],
    engine: ScienceBKT,
) -> dict[str, Any]:
    """One-pass matrix + at-risk + class-summary for the educator dashboard."""
    student_ids = list(scope.get("student_ids") or [])
    topic_ids = [t for t in (scope.get("topic_ids") or []) if t in engine.skill_map]
    known_topics = set(engine.skill_map.keys()) if engine.skill_map else set()
    unknown_topic_ids = [t for t in topic_ids if t not in known_topics]

    matrix = _compute_mastery_from_live_state(student_ids, topic_ids)
    known_users = _known_learner_ids(student_ids)
    alerts = _scan_current_topic_at_risk_alerts(known_users, topic_ids, engine)
    summary = _build_class_summary_payload(
        scope=scope,
        engine=engine,
        matrix=matrix,
        alerts=alerts,
    )

    payload: dict[str, Any] = {
        "success": True,
        "mode": "live_state",
        "student_ids": student_ids,
        "topic_ids": topic_ids,
        "unknown_topic_ids": unknown_topic_ids,
        "roster_count": len(student_ids),
        "topic_count": len(topic_ids),
        "mastery_matrix": matrix,
        "at_risk_students": alerts,
        "at_risk_count": len(alerts),
        "criteria": _risk_criteria_payload(),
        "class_summary": summary,
        "meta": {
            "optimized": True,
            "note": (
                "Single-pass classroom dashboard: matrix, at-risk, and summary "
                "share one roster resolve, one signal rebuild, and batched Postgres reads."
            ),
        },
    }
    for key in ("class_code", "class_name", "grade_level", "subject", "teacher_id"):
        if key in scope:
            payload[key] = scope[key]
    return payload


@app.get(
    "/api/v1/analytics/class-summary",
    tags=["Analytics"],
    summary="Classroom research summary (bands, gap, distractors, frustration)",
)
def analytics_class_summary(
    class_code: str = Query(
        ...,
        description="Classroom code from shared.classes (e.g. SCI-G7-492).",
        examples=["SCI-G7-492"],
    ),
) -> dict[str, Any]:
    """
    One-call classroom aggregates for the educator dashboard and evaluation metrics.

    Prefer ``GET /api/v1/analytics/classroom-dashboard`` when the UI also needs the
    mastery matrix and at-risk feed (avoids recomputing those twice).
    """
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    scope = _resolve_class_scope(class_code, engine)
    if not scope.get("success"):
        return {"success": False, "error": scope.get("error", "Invalid class_code.")}
    return _build_class_summary_payload(scope=scope, engine=engine)


@app.get(
    "/api/v1/analytics/classroom-dashboard",
    tags=["Analytics"],
    summary="Teacher dashboard bundle (matrix + at-risk + class-summary)",
)
def analytics_classroom_dashboard(
    class_code: str = Query(
        ...,
        description="Classroom code from shared.classes (e.g. SCI-G8-UKGE7X).",
        examples=["SCI-G8-UKGE7X"],
    ),
) -> dict[str, Any]:
    """
    Optimized Classroom Insights payload: mastery matrix, current-topic at-risk
    alerts, and research summary in **one** request / one compute pass.
    """
    engine = get_shared_bkt_engine()
    if not engine.skill_map:
        engine.initialize_skills()
    scope = _resolve_class_scope(class_code, engine)
    if not scope.get("success"):
        return {"success": False, "error": scope.get("error", "Invalid class_code.")}
    return _build_classroom_dashboard_payload(scope=scope, engine=engine)


@app.post(
    "/api/v1/dev/reset-learner-runtime",
    tags=["Analytics"],
    summary="Clear in-memory BKT state for a classroom seed (dev)",
)
def reset_learner_runtime(req: ResetLearnerRuntimeRequest) -> dict[str, Any]:
    """Used by classroom seed scripts so re-seeded quizzes start at the prior."""
    token = str(req.confirm).strip()
    if token not in _SEED_RUNTIME_TOKENS:
        return {"success": False, "error": "confirm token does not match."}
    ids = [str(uid).strip() for uid in req.learner_ids if str(uid).strip()]
    engine = get_shared_bkt_engine()
    dropped = engine.clear_runtime_state_for_learners(ids)
    _clear_runtime_buffers_for_learners(ids)
    skill_ids = [str(tid).strip() for tid in (req.skill_ids or []) if str(tid).strip()]
    dropped_params = engine.drop_cached_skill_params(skill_ids) if skill_ids else 0
    return {
        "success": True,
        "learner_ids": ids,
        "dropped_mastery_rows": dropped,
        "dropped_skill_param_cache": dropped_params,
    }

