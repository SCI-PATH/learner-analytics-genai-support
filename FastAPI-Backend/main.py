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
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Path as ApiPath
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from bkt_engine import ScienceBKT
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
            "name": "Mastery",
            "description": (
                "Read or update BKT mastery. Teammates who only need the current score "
                "and learner category should call **GET /api/v1/mastery/{user_id}/{topic_id}**."
            ),
        },
        {"name": "Tutor", "description": "Socratic chatbot hint endpoints."},
        {"name": "Engagement", "description": "Frustration cues from Component 3."},
        {
            "name": "Analytics",
            "description": (
                "Teacher dashboard (matrix, classroom at-risk) and student-facing "
                "focus areas / profile endpoints."
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
QuestionType = Literal["MCQ", "SHORT_ANSWER"]
DistractorTag = Literal["NEAR_MISS", "MISCONCEPTION", "COMPLETE_MISS"]
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
_replay_engine_cache: Optional[ScienceBKT] = None
_mastery_matrix_cache: dict[tuple[str, tuple[str, ...], tuple[str, ...]], dict[str, dict[str, float | None]]] = {}
_MASTER_MATRIX_CACHE_MAX = 32
_LIVE_STATE_DB = PROJECT_ROOT / "live_state_events.db"
_INTERACTION_LOG_PATH = PROJECT_ROOT / "interaction_logs.json"
_DISTRACTOR_TAGS_BY_TOPIC: dict[str, list[str]] = {}


def _distractor_tags_for_topic(topic_id: str) -> list[str]:
    tid = str(topic_id)
    if tid in _DISTRACTOR_TAGS_BY_TOPIC:
        return _DISTRACTOR_TAGS_BY_TOPIC[tid]
    return [
        f"Misconception related to {tid}",
        "Partial understanding of key concept",
        "Misapplied science rule",
    ]


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
                engine.predict_update(uid, topic, label, response_time_s)
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
    mode: str = "live_state",
    topic_ids: Optional[list[str]] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Return all at-risk topics for one learner (student focus areas).

    Unlike the classroom at-risk endpoint (one current topic per student), this
    scans every topic the learner has evidence on.
    """
    uid = str(user_id)
    focus_areas: list[dict[str, Any]] = []

    if mode == "replay_logs":
        engine = _get_replay_engine()
        all_topics = sorted(engine.skill_map.keys())
        topic_pool = [t for t in (topic_ids if topic_ids else all_topics) if t in engine.skill_map]
        logs_df = engine.logs_df.copy()
        logs_df["user_id"] = logs_df["user_id"].astype(str)
        logs_df["skill_name"] = logs_df["skill_name"].astype(str)
        u_df = logs_df[
            (logs_df["user_id"] == uid) & (logs_df["skill_name"].isin(set(topic_pool)))
        ].copy()
        if u_df.empty:
            return [], {"known_topics": all_topics, "topics_scanned": 0}

        u_df = u_df.sort_values(["order_id"]).reset_index(drop=True)
        work = deepcopy(engine)
        mastery_hist: dict[str, list[float]] = defaultdict(list)
        for row in u_df.itertuples(index=False):
            topic = str(getattr(row, "skill_name"))
            is_correct = int(getattr(row, "correct"))
            response_time = None
            if hasattr(row, "response_time"):
                try:
                    response_time = float(getattr(row, "response_time"))
                except (TypeError, ValueError):
                    response_time = None
            out = work.predict_update(uid, topic, is_correct, response_time)
            mastery_hist[topic].append(float(out.get("mastery_probability", 0.0)))

        topics_with_evidence = sorted(set(u_df["skill_name"].astype(str)))
        for topic in topics_with_evidence:
            mastery = float(work.get_current_mastery_probability(uid, topic))
            low_mastery = mastery < _MASTERY_LOW_THRESHOLD
            tail = mastery_hist.get(topic, [])[-3:]
            neg_velocity = len(tail) >= 3 and bool(tail[0] > tail[1] > tail[2])
            sig_tail = [
                float(getattr(r, "correct"))
                for r in u_df.itertuples(index=False)
                if str(getattr(r, "skill_name")) == topic
            ][-5:]
            recent_perf = (sum(sig_tail) / len(sig_tail)) if sig_tail else None
            weak_recent_perf = (recent_perf is not None) and (recent_perf < 0.4)
            alert = _compose_topic_risk_alert(
                student_id=uid,
                topic_id=topic,
                mastery=mastery,
                low_mastery=low_mastery,
                neg_velocity=neg_velocity,
                weak_recent_perf=weak_recent_perf,
                recent_signal_tail=tail,
                recent_performance_avg=recent_perf,
            )
            if alert:
                focus_areas.append(alert)
        focus_areas.sort(key=lambda a: a["risk_score"], reverse=True)
        return focus_areas, {
            "known_topics": all_topics,
            "topics_scanned": len(topics_with_evidence),
        }

    # live_state
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


def _record_chat_turn(
    user_id: str,
    topic_id: str,
    student_message: str,
    tutor_message: str,
    interaction_score: Optional[float] = None,
) -> None:
    record = {
        "user_id": str(user_id),
        "topic_id": str(topic_id),
        "student_message": str(student_message),
        "tutor_hint": str(tutor_message),
        "interaction_score": (
            None if interaction_score is None else float(max(0.0, min(1.0, interaction_score)))
        ),
        "critical_confusion": bool(
            interaction_score is not None and float(interaction_score) < 0.30
        ),
        "timestamp": datetime.now(UTC).isoformat(),
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
    return list(_assessment_attempts_by_user.get(str(user_id), []))


def _replay_user_attempts(
    user_id: str,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, list[float]], list[float]]:
    """
    Replay one learner's historical logs for profile analytics.

    Returns:
    - attempts in chronological order with mastery trajectory.
    - distractor frequency map (simulated deterministic tags for incorrect rows).
    - topic -> mastery trajectory list.
    - global mastery trajectory list.
    """
    engine = deepcopy(_get_replay_engine())
    logs_df = engine.logs_df.copy()
    u_df = logs_df[logs_df["user_id"].astype(str) == str(user_id)].copy()
    if u_df.empty:
        return [], {}, {}, []
    if "order_id" in u_df.columns:
        u_df = u_df.sort_values(["order_id"]).reset_index(drop=True)
    else:
        u_df = u_df.reset_index(drop=True)

    distractor_counts: dict[str, int] = defaultdict(int)
    attempts: list[dict[str, Any]] = []
    mastery_by_topic: dict[str, list[float]] = defaultdict(list)
    mastery_all: list[float] = []

    for idx, row in enumerate(u_df.itertuples(index=False)):
        topic = str(getattr(row, "skill_name"))
        is_correct = int(getattr(row, "correct"))
        response_time = None
        if hasattr(row, "response_time"):
            try:
                response_time = float(getattr(row, "response_time"))
            except (TypeError, ValueError):
                response_time = None

        out = engine.predict_update(str(user_id), topic, is_correct, response_time)
        mastery = float(out.get("mastery_probability", 0.0))
        mastery_by_topic[topic].append(mastery)
        mastery_all.append(mastery)
        attempts.append(
            {
                "topic_id": topic,
                "is_correct": bool(is_correct),
                "response_time_s": response_time,
                "mastery_probability": mastery,
            }
        )
        if not is_correct:
            tags = _distractor_tags_for_topic(topic)
            tag = tags[idx % len(tags)]
            distractor_counts[tag] += 1
    return attempts, dict(distractor_counts), dict(mastery_by_topic), mastery_all


def _get_replay_engine() -> ScienceBKT:
    """
    Shared read-only baseline engine for replay computations.

    Reusing one initialized engine avoids repeated CSV + skill initialization costs
    on each `/api/v1/mastery/matrix` request in replay mode.
    """
    global _replay_engine_cache
    if _replay_engine_cache is None:
        _replay_engine_cache = ScienceBKT(data_path="synthetic_logs.csv")
        _replay_engine_cache.initialize_skills()
        _replay_engine_cache.preload_calibrated_skill_params()
    return _replay_engine_cache


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
    """Verified quiz outcome; updates the same BKT state as the tutor."""

    user_id: str = Field(..., description="Student identifier")
    topic_id: str = Field(..., description="Curriculum topic / skill id, e.g. G6_S8_ELE_CIRCUITS")
    is_correct: bool = Field(..., description="Ground-truth correctness for this assessment item")
    question_type: Optional[QuestionType] = Field(
        None, description="MCQ or SHORT_ANSWER — drives analytics field interpretation"
    )
    distractor_tag: Optional[DistractorTag] = Field(
        None, description="Wrong MCQ error category: NEAR_MISS, MISCONCEPTION, or COMPLETE_MISS"
    )
    distractor_label: Optional[str] = Field(
        None, description="Short misconception phrase for Misconception Cloud aggregation"
    )
    similarity_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Short-answer semantic similarity to marking scheme"
    )
    response_time_s: Optional[float] = Field(None, ge=0.0, description="Seconds taken to answer")
    difficulty_level: Optional[float] = Field(None, description="Item difficulty on question-engine scale")
    subtopic_id: Optional[str] = Field(None, description="Optional finer curriculum label")
    question_id: Optional[str] = Field(None, description="Stable question item id for audit/dedupe")
    chosen_distractor_text: Optional[str] = Field(
        None, description="Full text of chosen wrong MCQ option when label is omitted"
    )
    source: Optional[str] = Field(None, description="Calling module identifier, e.g. question_engine_v1")


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
    """
    Request payload for classroom mastery matrix extraction.

    mode:
    - replay_logs: recompute mastery from synthetic_logs.csv using ScienceBKT logic
    - live_state: use only in-memory shared engine state (plus priors for unseen pairs)
    """

    student_ids: list[str] = Field(..., min_length=1, description="List of learner IDs")
    topic_ids: list[str] = Field(..., min_length=1, description="List of topic/skill IDs")
    mode: str = Field(
        "replay_logs",
        description="mastery source: replay_logs or live_state",
        pattern="^(replay_logs|live_state)$",
    )


class AtRiskStudentsRequest(BaseModel):
    """
    Optional filter controls for at-risk analytics.

    If not provided, the endpoint scans known users and all known topics.
    """

    student_ids: Optional[list[str]] = Field(None, description="Restrict scan to these students")
    topic_ids: Optional[list[str]] = Field(None, description="Restrict scan to these topics")
    mode: str = Field(
        "live_state",
        description="analytics source mode: live_state or replay_logs",
        pattern="^(replay_logs|live_state)$",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def _startup_init() -> None:
    _init_persistence()
    _hydrate_live_state_from_db()


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


@app.post("/tutor/hint")
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
        _record_chat_turn(
            req.user_id,
            str(result.get("topic_id") or req.topic_id),
            req.student_answer,
            str(result.get("hint_text") or ""),
            interaction_score=score_val,
        )
        _append_interaction_log(
            user_id=req.user_id,
            topic_id=str(result.get("topic_id") or req.topic_id),
            interaction_score=score_val,
            endpoint="/tutor/hint",
            frustration_metadata=_frustration_metadata_from_result(result),
        )
        if isinstance(score, (int, float)):
            topic_used = str(result.get("topic_id") or req.topic_id)
            _append_signal(req.user_id, topic_used, float(score))
    return result


@app.post("/tutor/hint-auto-topic")
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
        _record_chat_turn(
            req.user_id,
            resolved_topic,
            req.student_answer,
            str(result.get("hint_text") or ""),
            interaction_score=score_val,
        )
        _append_interaction_log(
            user_id=req.user_id,
            topic_id=resolved_topic,
            interaction_score=score_val,
            endpoint="/tutor/hint-auto-topic",
            frustration_metadata=_frustration_metadata_from_result(result),
        )
        if isinstance(score, (int, float)):
            topic_used = resolved_topic
            if topic_used:
                _append_signal(req.user_id, topic_used, float(score))
    return result


@app.post("/api/v1/assessment-submit", tags=["Mastery"])
def assessment_submit(req: AssessmentSubmitRequest) -> dict[str, Any]:
    """
    Record a **ground-truth** correct/incorrect outcome from the question engine.

    Calls ``predict_update`` on the shared ``ScienceBKT`` so quiz results and
    tutor dialogue update the **same** per-learner, per-skill mastery.
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
        "assessment_fields_persisted": {
            key: attempt_record.get(key)
            for key in (
                "question_type",
                "distractor_tag",
                "distractor_label",
                "similarity_score",
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


@app.post("/api/v1/engagement/frustration-cue")
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
    _persist_event(
        "frustration_cue",
        {
            "user_id": str(req.user_id),
            "topic_id": str(req.topic_id),
            "frustration_score": float(signal.frustration_score),
            "source": str(signal.source),
            "recorded_at": signal.recorded_at.isoformat(),
        },
    )
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


def _compute_mastery_by_replaying_logs(student_ids: list[str], topic_ids: list[str]) -> dict[str, dict[str, float]]:
    """
    Build a mastery matrix using the current BKT implementation on historical logs.

    This avoids fake data: it replays actual rows from synthetic_logs.csv through
    predict_update and then reads resulting P(L) values.
    """
    base_engine = _get_replay_engine()
    cache_key = ("replay_logs", tuple(student_ids), tuple(topic_ids))
    if cache_key in _mastery_matrix_cache:
        return deepcopy(_mastery_matrix_cache[cache_key])

    # Use a working copy so cached baseline state is not mutated by predict_update.
    engine = deepcopy(base_engine)
    selected_students = set(student_ids)
    selected_topics = set(topic_ids)
    known_topics = set(engine.skill_map.keys())

    logs_df = engine.logs_df.copy()
    filtered = logs_df[
        logs_df["user_id"].astype(str).isin(selected_students)
        & logs_df["skill_name"].astype(str).isin(selected_topics)
    ].copy()
    filtered = filtered.sort_values(["order_id"]).reset_index(drop=True)

    for row in filtered.itertuples(index=False):
        user_id = str(getattr(row, "user_id"))
        skill = str(getattr(row, "skill_name"))
        is_correct = int(getattr(row, "correct"))
        response_time = None
        if hasattr(row, "response_time"):
            try:
                response_time = float(getattr(row, "response_time"))
            except (TypeError, ValueError):
                response_time = None
        engine.predict_update(user_id, skill, is_correct, response_time)

    matrix: dict[str, dict[str, float]] = {}
    for sid in student_ids:
        matrix[sid] = {}
        for tid in topic_ids:
            if tid not in known_topics:
                # Unknown topic IDs are surfaced as null in API output instead of 500.
                matrix[sid][tid] = None
                continue
            matrix[sid][tid] = float(engine.get_current_mastery_probability(sid, tid))
    # Small bounded memoization for repeated dashboard calls.
    if len(_mastery_matrix_cache) >= _MASTER_MATRIX_CACHE_MAX:
        first_key = next(iter(_mastery_matrix_cache))
        _mastery_matrix_cache.pop(first_key, None)
    _mastery_matrix_cache[cache_key] = deepcopy(matrix)
    return matrix


def _compute_mastery_from_live_state(student_ids: list[str], topic_ids: list[str]) -> dict[str, dict[str, float]]:
    """
    Build mastery matrix from shared in-memory engine.

    Unseen learner-topic pairs resolve to topic priors via get_current_mastery_probability.
    """
    engine = get_shared_bkt_engine()
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


def _build_replay_at_risk_alerts(
    student_ids: Optional[list[str]],
    topic_ids: Optional[list[str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Replay synthetic logs and derive at-risk alerts from historical trajectories.

    In replay mode, velocity is checked on the last 3 mastery values for a user's
    selected current topic (strictly decreasing), which is meaningful for binary logs.
    """
    engine = _get_replay_engine()
    all_topics = sorted(engine.skill_map.keys())
    topic_pool = [t for t in (topic_ids if topic_ids else all_topics) if t in engine.skill_map]
    if not topic_pool:
        return [], {"known_topics": all_topics}

    logs_df = engine.logs_df.copy()
    logs_df["user_id"] = logs_df["user_id"].astype(str)
    logs_df["skill_name"] = logs_df["skill_name"].astype(str)

    users_all = sorted(set(logs_df["user_id"]))
    if student_ids:
        user_pool = [u for u in users_all if u in set(student_ids)]
    else:
        user_pool = users_all
    if not user_pool:
        return [], {"known_topics": all_topics}

    filt = logs_df[
        logs_df["user_id"].isin(user_pool)
        & logs_df["skill_name"].isin(set(topic_pool))
    ].copy()
    filt = filt.sort_values(["order_id"]).reset_index(drop=True)

    # Replay with trajectory capture for negative velocity on mastery values.
    work = deepcopy(engine)
    mastery_hist: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in filt.itertuples(index=False):
        uid = str(getattr(row, "user_id"))
        topic = str(getattr(row, "skill_name"))
        is_correct = int(getattr(row, "correct"))
        response_time = None
        if hasattr(row, "response_time"):
            try:
                response_time = float(getattr(row, "response_time"))
            except (TypeError, ValueError):
                response_time = None
        out = work.predict_update(uid, topic, is_correct, response_time)
        mastery_hist[(uid, topic)].append(float(out.get("mastery_probability", 0.0)))

    alerts: list[dict[str, Any]] = []
    for uid in user_pool:
        u_rows = filt[filt["user_id"] == uid]
        current_topic = str(u_rows.iloc[-1]["skill_name"]) if not u_rows.empty else topic_pool[0]
        mastery = float(work.get_current_mastery_probability(uid, current_topic))
        low_mastery = mastery < _MASTERY_LOW_THRESHOLD
        tail = mastery_hist.get((uid, current_topic), [])[-3:]
        neg_velocity = len(tail) >= 3 and bool(tail[0] > tail[1] > tail[2])
        sig_tail = [
            float(getattr(r, "correct"))
            for r in u_rows.itertuples(index=False)
            if str(getattr(r, "skill_name")) == current_topic
        ][-5:]
        recent_perf = (sum(sig_tail) / len(sig_tail)) if sig_tail else None
        weak_recent_perf = (recent_perf is not None) and (recent_perf < 0.4)

        # Simple + explainable predictive rule:
        # at-risk if at least 2 of the 3 signals are true.
        signal_count = int(low_mastery) + int(neg_velocity) + int(weak_recent_perf)
        if signal_count < 2:
            continue

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
            # Hard override for severe low-mastery + weak-recent cases.
            reasons.append("Critical Low Mastery")
            risk_score = max(risk_score, 85)

        alerts.append(
            {
                "student_id": uid,
                "topic_id": current_topic,
                "mastery_probability": round(mastery, 4),
                "mastery_category": _mastery_category_from_pl(mastery),
                "negative_velocity": bool(neg_velocity),
                "recent_signal_tail": [round(v, 4) for v in tail],
                "recent_performance_avg": (None if recent_perf is None else round(float(recent_perf), 4)),
                "signals_triggered": signal_count,
                "risk_score": int(min(100, max(0, risk_score))),
                "reason": "; ".join(reasons),
            }
        )
    alerts.sort(key=lambda a: a["risk_score"], reverse=True)
    return alerts, {"known_topics": all_topics}


@app.post("/api/v1/analytics/at-risk-students", tags=["Analytics"])
def analytics_at_risk_students(req: Optional[AtRiskStudentsRequest] = None) -> dict[str, Any]:
    """
    Return students predicted as at-risk for intervention.

    Criteria (current topic):
    - Low Mastery: P(L) < 0.4
    - Negative Velocity: last 3 tutor/assessment signals strictly decrease
    - High Slip Flag: fitted skill slip probability above threshold
    """
    mode = req.mode if req else "live_state"
    if mode == "replay_logs":
        alerts, _meta = _build_replay_at_risk_alerts(
            student_ids=(req.student_ids if req else None),
            topic_ids=(req.topic_ids if req else None),
        )
    else:
        engine = get_shared_bkt_engine()
        if not engine.skill_map:
            engine.initialize_skills()
        all_topics = sorted(engine.skill_map.keys())
        topic_pool = [t for t in (req.topic_ids if req and req.topic_ids else all_topics) if t in engine.skill_map]

        # Known students from logs + runtime state + streamed event memory.
        logs_users = set(engine.logs_df["user_id"].astype(str).unique())
        state_users = {str(u) for (u, _t) in engine.student_state.keys()}
        event_users = set(_latest_topic_by_user.keys())
        known_users = sorted(logs_users | state_users | event_users)
        if req and req.student_ids:
            known_users = [u for u in known_users if u in set(req.student_ids)]

        alerts = []
        for uid in known_users:
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
        "mode": mode,
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
    mode: str = "live_state",
) -> dict[str, Any]:
    """
    **Student-facing** list of at-risk / focus topics for one learner.

    Use this on the student profile page so learners can see where they need more practice.
    Teachers should continue using ``POST /api/v1/analytics/at-risk-students`` for the
    classroom overview.

    Unlike the classroom endpoint (one *current* topic per student), this scans **all**
    topics the learner has evidence on (attempts, tutor signals, or synthetic-log rows).

    Same risk rule as teacher alerts: at least 2 of
    low mastery / declining velocity / weak recent performance.
    """
    if mode not in {"replay_logs", "live_state"}:
        return {"success": False, "error": "mode must be replay_logs or live_state"}

    focus_areas, meta = _build_student_focus_areas(str(user_id), mode=mode)
    return {
        "success": True,
        "mode": mode,
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
    Return mastery probabilities for a classroom slice (students x topics).

    Use ``mode=replay_logs`` for meaningful baseline values from synthetic logs.
    Use ``mode=live_state`` to inspect the process in-memory state produced by
    assessment/tutor events since startup.
    """
    if req.mode == "replay_logs":
        matrix = _compute_mastery_by_replaying_logs(req.student_ids, req.topic_ids)
        known_topics = set(_get_replay_engine().skill_map.keys())
    else:
        matrix = _compute_mastery_from_live_state(req.student_ids, req.topic_ids)
        shared = get_shared_bkt_engine()
        known_topics = set(shared.skill_map.keys()) if shared.skill_map else set()
    unknown_topic_ids = [t for t in req.topic_ids if t not in known_topics]
    return {
        "success": True,
        "mode": req.mode,
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
def analytics_student_profile(user_id: str, mode: str = "replay_logs") -> dict[str, Any]:
    """
    Deep-dive profile for one learner.

    mode:
    - replay_logs: derive profile from synthetic_logs.csv replay + in-memory cues/chat
    - live_state: derive BKT values from current shared engine state; assessment analytics prefer
      live Question Engine attempts when present, else synthetic-log fallback.

    Also embeds ``focus_areas`` (same payload as
    ``GET /api/v1/analytics/student-focus-areas/{user_id}``) for one-call profile pages.
    """
    if mode not in {"replay_logs", "live_state"}:
        return {"success": False, "error": "mode must be replay_logs or live_state"}

    replay_engine = _get_replay_engine()
    known_topics = sorted(replay_engine.skill_map.keys())
    attempts, simulated_distractor_counts, mastery_by_topic, mastery_all = _replay_user_attempts(
        user_id
    )
    live_attempts = _live_attempts_for_user(user_id)
    live_distractor_counts = _live_distractor_counts(user_id)
    use_live_distractors = bool(live_distractor_counts)
    distractor_counts = live_distractor_counts if use_live_distractors else simulated_distractor_counts
    distractor_source = (
        "question_engine_live" if use_live_distractors else "simulated_from_incorrect_attempts_in_synthetic_logs"
    )
    profile_attempts = live_attempts if live_attempts else attempts

    if mode == "live_state":
        engine = get_shared_bkt_engine()
        if not engine.skill_map:
            engine.initialize_skills()
    else:
        engine = deepcopy(replay_engine)
        # Re-apply user attempts so profile topic values match replayed trajectory.
        for attempt in attempts:
            engine.predict_update(
                str(user_id),
                str(attempt["topic_id"]),
                1 if attempt["is_correct"] else 0,
                attempt.get("response_time_s"),
            )

    bkt_parameters: list[dict[str, Any]] = []
    for topic_id in known_topics:
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

    # Topic-level time-on-task trend from synthetic logs (simple slope over last 10 points).
    topic_time_trends: list[dict[str, Any]] = []
    u_df = replay_engine.logs_df[replay_engine.logs_df["user_id"].astype(str) == str(user_id)].copy()
    for topic_id in known_topics:
        t_df = u_df[u_df["skill_name"].astype(str) == topic_id]
        vals = pd.to_numeric(t_df.get("response_time"), errors="coerce").dropna().tolist() if "response_time" in t_df else []
        tail = vals[-10:]
        if len(tail) >= 2:
            slope = (tail[-1] - tail[0]) / float(len(tail) - 1)
            trend = "increasing" if slope > 0.15 else ("decreasing" if slope < -0.15 else "stable")
        else:
            slope = 0.0
            trend = "stable"
        topic_time_trends.append(
            {
                "topic_id": topic_id,
                "avg_time_on_task_s": round(float(sum(tail) / len(tail)), 3) if tail else None,
                "last_10_time_on_task_s": [round(float(v), 3) for v in tail],
                "trend": trend,
            }
        )

    f_values = [
        v
        for (uid, _topic), seq in _frustration_history.items()
        if uid == str(user_id)
        for v in seq
    ]
    avg_frustration = round(float(sum(f_values) / len(f_values)), 4) if f_values else None

    top_distractors = sorted(
        [{"tag": tag, "count": int(count)} for tag, count in distractor_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    chat_tail = list(_chat_history_by_user.get(str(user_id), []))[-5:]
    if live_attempts:
        timeline_tail = [
            {
                "topic_id": str(row.get("topic_id") or ""),
                "is_correct": bool(row.get("is_correct")),
                "response_time_s": row.get("response_time_s"),
                "mastery_probability": row.get("updated_mastery_probability"),
                "distractor_label": row.get("distractor_label"),
                "question_type": row.get("question_type"),
            }
            for row in live_attempts[-10:]
        ]
    else:
        timeline_tail = attempts[-10:]
    engagement_tail = _load_interaction_logs_for_user(user_id, limit=10)
    engagement_scores = [
        float(x.get("interaction_score"))
        for x in engagement_tail
        if isinstance(x.get("interaction_score"), (int, float))
    ]
    critical_confusion_turns = [
        row for row in chat_tail if bool(row.get("critical_confusion")) is True
    ]
    focus_areas, focus_meta = _build_student_focus_areas(str(user_id), mode=mode)
    return {
        "success": True,
        "mode": mode,
        "user_id": str(user_id),
        "topics_covered_count": len([t for t in mastery_by_topic.keys() if mastery_by_topic[t]]),
        "bkt_parameters": bkt_parameters,
        "focus_areas": focus_areas,
        "focus_areas_count": len(focus_areas),
        "assessment_insights": {
            "most_frequent_distractor_tags": top_distractors,
            "attempts_count": len(profile_attempts),
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
            "overall_mastery_tail": [round(v, 4) for v in mastery_all[-10:]],
            "focus_areas_topics_scanned": focus_meta.get("topics_scanned", 0),
            "focus_areas_endpoint": f"/api/v1/analytics/student-focus-areas/{user_id}",
        },
    }

