"""Postgres writes for Component 4 analytics tables (DBeaver / shared DB).

Connection string lives in the repo-root ``.env`` as ``DATABASE_URL``.
DBeaver is only a client — FastAPI uses the same host/db/user/password.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

try:
    import psycopg
except ImportError:  # pragma: no cover - optional until pip install
    psycopg = None  # type: ignore[assignment]


ASSESSMENT_ATTEMPTS_TABLE = "learner_analytics.assessment_attempts"
BKT_SKILL_PARAMS_TABLE = "learner_analytics.bkt_skill_params"
BKT_MASTERY_TABLE = "learner_analytics.bkt_mastery"
TUTOR_TURNS_TABLE = "learner_analytics.tutor_turns"
FRUSTRATION_CUES_TABLE = "learner_analytics.frustration_cues"


def _database_url() -> Optional[str]:
    url = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "").strip()
    if not url or url.startswith("#"):
        return None
    lower = url.lower()
    if "neon.tech" in lower and "sslmode=" not in lower:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def postgres_configured() -> bool:
    return _database_url() is not None


def _clip(value: Any, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return text[:max_len]


def score_reasoning_from_attempt(record: dict[str, Any]) -> Optional[str]:
    """Map ``detailed_explanation`` onto the table's ``score_reasoning`` column."""
    explanation = record.get("detailed_explanation")
    if explanation:
        return str(explanation)
    return None


def _missed_blanks_value(record: dict[str, Any]) -> Any:
    blanks = record.get("missed_blanks")
    if not blanks:
        return None
    if isinstance(blanks, str):
        try:
            blanks = json.loads(blanks)
        except json.JSONDecodeError:
            return blanks
    if psycopg is not None:
        from psycopg.types.json import Jsonb

        return Jsonb(blanks)
    return json.dumps(blanks, ensure_ascii=True)


def insert_assessment_attempt(record: dict[str, Any]) -> dict[str, Any]:
    """Insert one scored attempt. Does not update BKT.

    Returns:
        ``{"ok": True, "attempt_id": int, "created_at": str}`` on success,
        ``{"ok": False, "skipped": True, "reason": str}`` if unconfigured,
        ``{"ok": False, "error": str}`` on failure.
    """
    url = _database_url()
    if not url:
        return {
            "ok": False,
            "skipped": True,
            "reason": (
                "DATABASE_URL is not set in .env. Add your DBeaver Postgres "
                "credentials there, then restart uvicorn."
            ),
        }
    if psycopg is None:
        return {
            "ok": False,
            "error": "psycopg is not installed. Run: pip install 'psycopg[binary]'",
        }

    sql = f"""
        INSERT INTO {ASSESSMENT_ATTEMPTS_TABLE} (
            learner_id,
            topic_id,
            is_correct,
            question_type,
            distractor_tag,
            distractor_label,
            chosen_distractor_text,
            similarity_score,
            score_reasoning,
            error_category,
            missed_blanks,
            response_time_s,
            difficulty_level,
            subtopic_id,
            question_id,
            source,
            p_l_after
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING attempt_id, created_at
    """
    params = (
        _clip(record.get("user_id") or record.get("learner_id"), 64),
        _clip(record.get("topic_id"), 64),
        bool(record.get("is_correct")),
        _clip(record.get("question_type"), 30),
        _clip(record.get("distractor_tag"), 30),
        _clip(record.get("distractor_label"), 255),
        record.get("chosen_distractor_text"),
        record.get("similarity_score"),
        score_reasoning_from_attempt(record),
        _clip(record.get("error_category"), 40),
        _missed_blanks_value(record),
        record.get("response_time_s"),
        record.get("difficulty_level"),
        _clip(record.get("subtopic_id"), 100),
        _clip(record.get("question_id"), 100),
        _clip(record.get("source"), 50),
        record.get("updated_mastery_probability"),
    )
    try:
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    attempt_id, created_at = row if row else (None, None)
    return {
        "ok": True,
        "attempt_id": int(attempt_id) if attempt_id is not None else None,
        "created_at": created_at.isoformat() if created_at is not None else None,
        "table": ASSESSMENT_ATTEMPTS_TABLE,
    }


def _connect():
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if psycopg is None:
        raise RuntimeError("psycopg is not installed")
    return psycopg.connect(url)


def list_bkt_skill_ids() -> list[str]:
    """Topic IDs that have rows in ``bkt_skill_params``."""
    if not postgres_configured() or psycopg is None:
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT topic_id FROM {BKT_SKILL_PARAMS_TABLE} ORDER BY topic_id"
                )
                return [str(row[0]) for row in cur.fetchall() if row and row[0]]
    except Exception:
        return []


def fetch_skill_params(topic_id: str) -> Optional[dict[str, float]]:
    """Load prior/learn/guess/slip/forget for one topic from Postgres."""
    if not postgres_configured() or psycopg is None:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT prior_p, learn_p, guess_p, slip_p, forget_p
                    FROM {BKT_SKILL_PARAMS_TABLE}
                    WHERE topic_id = %s
                    """,
                    (str(topic_id),),
                )
                row = cur.fetchone()
    except Exception:
        return None
    if not row:
        return None
    prior_p, learn_p, guess_p, slip_p, forget_p = row
    return {
        "prior": float(prior_p),
        "learn": float(learn_p),
        "guess": float(guess_p),
        "slip": float(slip_p),
        "forget": float(forget_p if forget_p is not None else 0.0),
    }


def fetch_mastery_state(learner_id: str, topic_id: str) -> Optional[dict[str, Any]]:
    """Load persisted BKT state for one learner × topic."""
    rows = fetch_mastery_states_for_learner(learner_id, topic_ids=[str(topic_id)])
    return rows.get(str(topic_id))


def fetch_mastery_states_for_learner(
    learner_id: str,
    *,
    topic_ids: Optional[list[str]] = None,
) -> dict[str, dict[str, Any]]:
    """Load all (or selected) persisted BKT rows for one learner in a single query."""
    if not postgres_configured() or psycopg is None:
        return {}
    sql = f"""
        SELECT topic_id, p_l, attempts, consecutive_incorrect, at_risk
        FROM {BKT_MASTERY_TABLE}
        WHERE learner_id = %s
    """
    params: list[Any] = [str(learner_id)]
    if topic_ids:
        ids = [str(t) for t in topic_ids if str(t).strip()]
        if not ids:
            return {}
        sql += " AND topic_id = ANY(%s)"
        params.append(ids)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
    except Exception:
        return {}

    out: dict[str, dict[str, Any]] = {}
    for topic_id, p_l, attempts, consecutive_incorrect, at_risk in rows:
        out[str(topic_id)] = {
            "mastery": float(p_l),
            "attempts": int(attempts or 0),
            "consecutive_incorrect": int(consecutive_incorrect or 0),
            "at_risk": bool(at_risk),
        }
    return out


def upsert_mastery_state(
    *,
    learner_id: str,
    topic_id: str,
    p_l: float,
    attempts: int,
    consecutive_incorrect: int,
    at_risk: bool,
) -> dict[str, Any]:
    """Insert or update ``learner_analytics.bkt_mastery``."""
    if not postgres_configured():
        return {
            "ok": False,
            "skipped": True,
            "reason": "DATABASE_URL is not set in .env.",
        }
    if psycopg is None:
        return {"ok": False, "error": "psycopg is not installed."}
    sql = f"""
        INSERT INTO {BKT_MASTERY_TABLE} (
            learner_id, topic_id, p_l, attempts, consecutive_incorrect, at_risk, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (learner_id, topic_id) DO UPDATE SET
            p_l = EXCLUDED.p_l,
            attempts = EXCLUDED.attempts,
            consecutive_incorrect = EXCLUDED.consecutive_incorrect,
            at_risk = EXCLUDED.at_risk,
            updated_at = NOW()
        RETURNING learner_id, topic_id, p_l, attempts, consecutive_incorrect, at_risk, updated_at
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        _clip(learner_id, 64),
                        _clip(topic_id, 64),
                        float(p_l),
                        int(attempts),
                        int(consecutive_incorrect),
                        bool(at_risk),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not row:
        return {"ok": False, "error": "upsert returned no row"}
    learner, topic, p_l_out, att, streak, risk, updated_at = row
    return {
        "ok": True,
        "table": BKT_MASTERY_TABLE,
        "learner_id": str(learner),
        "topic_id": str(topic),
        "p_l": float(p_l_out),
        "attempts": int(att),
        "consecutive_incorrect": int(streak),
        "at_risk": bool(risk),
        "updated_at": updated_at.isoformat() if updated_at is not None else None,
    }


def insert_tutor_turn(record: dict[str, Any]) -> dict[str, Any]:
    """Insert one Socratic tutor turn into ``learner_analytics.tutor_turns``."""
    if not postgres_configured():
        return {"ok": False, "skipped": True, "reason": "DATABASE_URL is not set in .env."}
    if psycopg is None:
        return {"ok": False, "error": "psycopg is not installed."}

    sql = f"""
        INSERT INTO {TUTOR_TURNS_TABLE} (
            learner_id,
            topic_id,
            student_message,
            tutor_hint,
            persona_id,
            hint_mode,
            interaction_score,
            critical_confusion,
            topic_inferred,
            frustration_level_used,
            frustration_source_tag,
            frustration_effective_score,
            bkt_updated,
            endpoint
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING turn_id, created_at
    """
    params = (
        _clip(record.get("user_id") or record.get("learner_id"), 64),
        _clip(record.get("topic_id"), 64),
        str(record.get("student_message") or ""),
        str(record.get("tutor_hint") or ""),
        _clip(record.get("persona_id"), 50),
        _clip(record.get("hint_mode"), 30),
        record.get("interaction_score"),
        bool(record.get("critical_confusion")),
        bool(record.get("topic_inferred")),
        _clip(record.get("frustration_level_used"), 30),
        _clip(record.get("frustration_source_tag"), 50),
        record.get("frustration_effective_score"),
        bool(record.get("bkt_updated")),
        _clip(record.get("endpoint"), 80),
    )
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    turn_id, created_at = row if row else (None, None)
    return {
        "ok": True,
        "turn_id": int(turn_id) if turn_id is not None else None,
        "created_at": created_at.isoformat() if created_at is not None else None,
        "table": TUTOR_TURNS_TABLE,
    }


def insert_frustration_cue(record: dict[str, Any]) -> dict[str, Any]:
    """Insert one engagement frustration cue."""
    if not postgres_configured():
        return {"ok": False, "skipped": True, "reason": "DATABASE_URL is not set in .env."}
    if psycopg is None:
        return {"ok": False, "error": "psycopg is not installed."}

    recorded_at = record.get("recorded_at")
    sql = f"""
        INSERT INTO {FRUSTRATION_CUES_TABLE} (
            learner_id,
            topic_id,
            frustration_score,
            source,
            recorded_at
        ) VALUES (%s, %s, %s, %s, COALESCE(%s, NOW()))
        RETURNING cue_id, recorded_at, created_at
    """
    params = (
        _clip(record.get("user_id") or record.get("learner_id"), 64),
        _clip(record.get("topic_id"), 64),
        float(record.get("frustration_score") or 0.0),
        _clip(record.get("source"), 50) or "engagement_module",
        recorded_at,
    )
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    cue_id, recorded_at_out, created_at = row if row else (None, None, None)
    return {
        "ok": True,
        "cue_id": int(cue_id) if cue_id is not None else None,
        "recorded_at": recorded_at_out.isoformat() if recorded_at_out is not None else None,
        "created_at": created_at.isoformat() if created_at is not None else None,
        "table": FRUSTRATION_CUES_TABLE,
    }


def fetch_tutor_turns_for_learner(learner_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Recent tutor turns for engagement timeline / chat review."""
    if not postgres_configured() or psycopg is None:
        return []
    lim = max(1, min(int(limit), 100))
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        learner_id,
                        topic_id,
                        student_message,
                        tutor_hint,
                        persona_id,
                        hint_mode,
                        interaction_score,
                        critical_confusion,
                        topic_inferred,
                        frustration_level_used,
                        frustration_source_tag,
                        frustration_effective_score,
                        bkt_updated,
                        endpoint,
                        created_at
                    FROM {TUTOR_TURNS_TABLE}
                    WHERE learner_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (str(learner_id), lim),
                )
                rows = cur.fetchall()
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        (
            lid,
            topic_id,
            student_message,
            tutor_hint,
            persona_id,
            hint_mode,
            interaction_score,
            critical_confusion,
            topic_inferred,
            frustration_level_used,
            frustration_source_tag,
            frustration_effective_score,
            bkt_updated,
            endpoint,
            created_at,
        ) = row
        ts = created_at.isoformat() if created_at is not None else None
        out.append(
            {
                "user_id": str(lid),
                "topic_id": str(topic_id),
                "student_message": student_message,
                "tutor_hint": tutor_hint,
                "persona_id": persona_id,
                "hint_mode": hint_mode,
                "interaction_score": interaction_score,
                "critical_confusion": bool(critical_confusion),
                "topic_inferred": bool(topic_inferred),
                "frustration_level_used": frustration_level_used,
                "source_tag": frustration_source_tag,
                "effective_score": frustration_effective_score,
                "bkt_updated": bool(bkt_updated),
                "endpoint": endpoint,
                "timestamp": ts,
            }
        )
    out.reverse()
    return out


def fetch_frustration_scores_for_learner(learner_id: str) -> list[float]:
    """All frustration cue scores for one learner (engagement metrics)."""
    if not postgres_configured() or psycopg is None:
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT frustration_score
                    FROM {FRUSTRATION_CUES_TABLE}
                    WHERE learner_id = %s
                    ORDER BY recorded_at ASC
                    """,
                    (str(learner_id),),
                )
                return [float(row[0]) for row in cur.fetchall() if row and row[0] is not None]
    except Exception:
        return []


def list_distinct_learner_ids() -> list[str]:
    """Learner IDs seen in assessment, mastery, or tutor tables."""
    if not postgres_configured() or psycopg is None:
        return []
    sql = f"""
        SELECT DISTINCT learner_id FROM (
            SELECT learner_id FROM {ASSESSMENT_ATTEMPTS_TABLE}
            UNION
            SELECT learner_id FROM {BKT_MASTERY_TABLE}
            UNION
            SELECT learner_id FROM {TUTOR_TURNS_TABLE}
        ) AS ids
        ORDER BY learner_id
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return [str(row[0]) for row in cur.fetchall() if row and row[0]]
    except Exception:
        return []


def fetch_assessment_attempts_for_learner(
    learner_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Recent assessment attempts for profile / misconception analytics."""
    if not postgres_configured() or psycopg is None:
        return []
    lim = max(1, min(int(limit), 2000))
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        learner_id,
                        topic_id,
                        is_correct,
                        question_type,
                        distractor_tag,
                        distractor_label,
                        chosen_distractor_text,
                        similarity_score,
                        score_reasoning,
                        error_category,
                        missed_blanks,
                        response_time_s,
                        difficulty_level,
                        subtopic_id,
                        question_id,
                        source,
                        p_l_after,
                        created_at
                    FROM {ASSESSMENT_ATTEMPTS_TABLE}
                    WHERE learner_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (str(learner_id), lim),
                )
                rows = cur.fetchall()
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        (
            lid,
            topic_id,
            is_correct,
            question_type,
            distractor_tag,
            distractor_label,
            chosen_distractor_text,
            similarity_score,
            score_reasoning,
            error_category,
            missed_blanks,
            response_time_s,
            difficulty_level,
            subtopic_id,
            question_id,
            source,
            p_l_after,
            created_at,
        ) = row
        record: dict[str, Any] = {
            "user_id": str(lid),
            "topic_id": str(topic_id),
            "is_correct": bool(is_correct),
            "label": 1 if bool(is_correct) else 0,
            "timestamp": created_at.isoformat() if created_at is not None else None,
        }
        if question_type is not None:
            record["question_type"] = question_type
        if distractor_tag is not None:
            record["distractor_tag"] = distractor_tag
        if distractor_label is not None:
            record["distractor_label"] = distractor_label
        if chosen_distractor_text is not None:
            record["chosen_distractor_text"] = chosen_distractor_text
        if similarity_score is not None:
            record["similarity_score"] = float(similarity_score)
        if score_reasoning is not None:
            record["detailed_explanation"] = score_reasoning
        if error_category is not None:
            record["error_category"] = error_category
        if missed_blanks is not None:
            record["missed_blanks"] = missed_blanks
        if response_time_s is not None:
            record["response_time_s"] = float(response_time_s)
        if difficulty_level is not None:
            record["difficulty_level"] = difficulty_level
        if subtopic_id is not None:
            record["subtopic_id"] = subtopic_id
        if question_id is not None:
            record["question_id"] = question_id
        if source is not None:
            record["source"] = source
        if p_l_after is not None:
            record["updated_mastery_probability"] = float(p_l_after)
        out.append(record)
    return out
