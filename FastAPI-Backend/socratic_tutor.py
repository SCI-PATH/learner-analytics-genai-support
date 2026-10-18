"""
Socratic tutoring hints grounded in BKT mastery and the local syllabus RAG index.

**Mastery architecture (single state per learner per skill):** There is one
process-wide ``ScienceBKT`` and one ``student_state[(user_id, skill)]`` trajectory.
- **Assessment / quiz** (``POST /api/v1/assessment-submit`` in ``main.py``): pass
  verified ``is_correct`` into ``predict_update`` — ground-truth labels.
- **Dialogue** (this module): does **not** update BKT by default
  (``TUTOR_BKT_POLICY=quiz_only``). Set ``strict`` / ``legacy`` to allow
  dialogue-derived updates. Ambiguous scores skip updates under ``strict``.
  Missing/invalid scores → **no** BKT update that turn.

Uses Groq via langchain_groq (env-based). The tutor follows a state-aware Socratic
framework (correction-first when needed, mastery-tuned scaffolding).

Install:
    pip install langchain-groq python-dotenv

Environment:
  GROQ_API_KEY (loaded from .env)
  GROQ_MODEL_NAME: Groq model id (default ``openai/gpt-oss-120b``).
  TUTOR_LLM_MAX_TOKENS: optional int (default ``512``).
  TUTOR_BKT_POLICY: how dialogue updates BKT — ``quiz_only`` (default): never
    update BKT from chat; use ``/api/v1/assessment-submit`` only.
    ``strict``: only clear correct/incorrect scores update mastery; ambiguous
    mid scores skip updates.
    ``legacy``: old rule (score×0.5 then ≥0.25 ⇒ correct — very optimistic).
  TUTOR_LLM_TEMPERATURE: optional float (default ``0.35`` for steadier scoring).
  TUTOR_DEFAULT_PERSONA: optional persona_id if client omits one and frustration
    is not high (else random per turn). High frustration always uses
    practical_encourager, even when the client sends persona_id.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from dotenv import dotenv_values, load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from bkt_engine import ScienceBKT
from curriculum_topics import FALLBACK_TOPIC_ID, normalize_topic_id
from knowledge_base import _TOPIC_KEYWORDS, retrieve_context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = PROJECT_ROOT / ".env"


def _load_env() -> None:
    """Load ``learner-analytics-genai-support/.env``.

    Uses ``utf-8-sig`` so a UTF-8 BOM (common after Windows editors rewrite
    the file) does not rename the first key. If ``GROQ_API_KEY`` is already
    in the process environment but blank, the file value wins.
    """
    load_dotenv(_ENV_PATH, encoding="utf-8-sig")
    file_vals = dotenv_values(_ENV_PATH, encoding="utf-8-sig")
    groq = str(file_vals.get("GROQ_API_KEY") or "").strip()
    if groq and not os.environ.get("GROQ_API_KEY", "").strip():
        os.environ["GROQ_API_KEY"] = groq


HintMode = Literal["scaffold", "balanced", "nudge"]
PersonaId = Literal["practical_encourager", "analytical_coach", "curious_explorer"]

_PERSONA_LABELS: dict[str, str] = {
    "practical_encourager": "The Practical Encourager",
    "analytical_coach": "The Analytical Coach",
    "curious_explorer": "The Curious Explorer",
}
_VALID_PERSONAS: tuple[str, ...] = tuple(_PERSONA_LABELS.keys())
_PERSONA_ALIASES: dict[str, str] = {
    "practical_encourager": "practical_encourager",
    "practical": "practical_encourager",
    "encourager": "practical_encourager",
    "the_practical_encourager": "practical_encourager",
    "analytical_coach": "analytical_coach",
    "analytical": "analytical_coach",
    "coach": "analytical_coach",
    "the_analytical_coach": "analytical_coach",
    "curious_explorer": "curious_explorer",
    "curious": "curious_explorer",
    "explorer": "curious_explorer",
    "the_curious_explorer": "curious_explorer",
}

# 3 (persona) × 3 (BKT hint mode) specialized coaching configurations.
_PERSONA_STATE_MATRIX: dict[str, dict[str, str]] = {
    "practical_encourager": {
        "scaffold": (
            "PERSONA × MODE: Practical Encourager · SCAFFOLD (P(L) < 0.5).\n"
            "- If they just answered you: verdict first (Yes that's right / Not quite / Partly).\n"
            "- Then one everyday comparison (kitchen, sport, weather). Withhold extra teaching.\n"
            "- One small real-world prediction question."
        ),
        "balanced": (
            "PERSONA × MODE: Practical Encourager · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- If they just answered you: verdict first, then one short contrast (this vs that).\n"
            "- Do not re-teach the whole topic.\n"
            "- One which-situation question."
        ),
        "nudge": (
            "PERSONA × MODE: Practical Encourager · NUDGE (P(L) > 0.8).\n"
            "- If they just answered you: one-word verdict, then one \"what would you notice?\" question.\n"
            "- No analogy chains."
        ),
    },
    "analytical_coach": {
        "scaffold": (
            "PERSONA × MODE: Analytical Coach · SCAFFOLD (P(L) < 0.5).\n"
            "- If they just answered you: first line is a short verdict, then 3 numbered clues.\n"
            "- The 3 lines must NOT state the why / what / how they asked for.\n"
            "- Then ONE short check question on its own last line."
        ),
        "balanced": (
            "PERSONA × MODE: Analytical Coach · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- If they just answered you: verdict line first, then 3 numbered contrast clues.\n"
            "- Do NOT name the finished rule. Each step ≤12 words. Then ONE question."
        ),
        "nudge": (
            "PERSONA × MODE: Analytical Coach · NUDGE (P(L) > 0.8).\n"
            "- If they just answered you: verdict line first, then 3 numbered prediction clues.\n"
            "- Still withhold the textbook sentence. Then ONE \"what happens next?\" question."
        ),
    },
    "curious_explorer": {
        "scaffold": (
            "PERSONA × MODE: Curious Explorer · SCAFFOLD (P(L) < 0.5).\n"
            "- If they just answered you: verdict first, then one clue.\n"
            "- Then one \"what might be going on?\" question. No extra puzzle setup."
        ),
        "balanced": (
            "PERSONA × MODE: Curious Explorer · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- If they just answered you: verdict first, then one \"what if\" that splits two close ideas."
        ),
        "nudge": (
            "PERSONA × MODE: Curious Explorer · NUDGE (P(L) > 0.8).\n"
            "- If they just answered you: verdict first, then one \"suppose … then what changes?\" question."
        ),
    },
}

_SOCRATIC_GUARDRAILS = """
--- NON-NEGOTIABLE SOCRATIC GUARDRAILS (all personas, all modes) ---
1. PRIVATE GROUNDING: Curriculum snippets in the user message are YOUR private notes
   (``science_syllabus_g6_g9``). Speak as a tutor who already knows this. Never invent facts
   outside those notes. If they are silent, say you are unsure—without mentioning a book,
   excerpt, PDF, or retrieval.
2. BAN META-COMMENTARY IN hint_text: Never say \"the excerpt\", \"the text\", \"the textbook\",
   \"the passage\", \"the reading\", \"according to the text\", \"the curriculum says\", or
   mention filenames, pages, figures, or snippet IDs.
3. GRADE 6–9 VOICE: Write for a 11–15 year old. Short words. One idea. No jargon unless you
   replace it with a 3–4 word plain meaning. No essay tone.
4. FOLLOW-UP = SCIENCE, NOT READING: One closing question about what happens in the real world.
   BAD: \"What might the text suggest happens when the wet stick touches the wire?\"
   GOOD: \"If the stick is wet, can electricity still travel along it?\"
5. SOCRATIC — NEVER GIVE THE ANSWER (every persona, every mode, every question):
   You are not a textbook. The student must arrive at the fact by answering YOUR question.
   If a marker could tick THEIR question from your hint_text alone, it is too direct.
   This covers why / what / how / when / where / which / need / used for / define —
   including Analytical Coach's 3 steps (those are riddles, not three facts).
   BAD: \"Fish use gills to take oxygen from water.\"
   BAD: \"Acidic solutions turn blue litmus paper red.\"
   BAD: \"1. Sodium is in table salt  2. It helps nerves  3. It balances body fluids\"
   GOOD: \"Fish stay underwater and cannot use lungs like you. What gas in the water
   must reach their blood?\"
6. LAYOUT: Practical Encourager and Curious Explorer — no lists, bullets, or mini-lessons.
   Analytical Coach ONLY — exactly three numbered lines (`1.` `2.` `3.`), each ≤12 simple
   words, then ONE short question on the next line. If they just answered you, put ONE
   short verdict line BEFORE the numbered list (not instead of it).
7. ONE QUESTION: hint_text contains exactly ONE question mark. Never a second question
   (no \"and why?\", no \"what else?\", no stacked ?). The follow-up is the last line only.
8. BREVITY: Other personas: 1–2 short sentences + that question (hard cap 50 words).
   Analytical Coach: optional verdict + 3 short steps + one question (about 45 words total).
9. VARIETY: Do NOT open with \"Great job!\", \"Good start!\", \"That's a great start!\",
   or \"Excellent question!\". When they answered your last question, DO open with a
   verdict: \"Yes — that's right.\", \"Not quite.\", or \"Partly right.\"
10. VALIDATE ATTEMPTS BEFORE MOVING ON: If their latest message answers YOUR previous
   follow-up, sentence 1 must say whether it is correct, not quite, or partly right.
   Only then give the next clue and one new question. If they are wrong, do not dump
   the correct fact — say not quite, give a smaller clue, and ask again.
11. JSON ONLY: Return a single JSON object with hint_text and interaction_score—no extra keys.
""".strip()

# Few-shot demonstrations: native tutor voice (no meta \"text/excerpt\" references).
_FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "I don't get conductors vs insulators.",
        "hint": "Some kitchen tools let electricity pass and some block it. Would a metal spoon or a rubber spatula be safer near a socket?",
    },
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "Give me a hint",
        "hint": "A sharp-smelling gas can come from rotting waste, not from a kitchen tap. Could a compost heap let that gas out?",
    },
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "How do we identify an acid with litmus paper?",
        "hint": "Litmus comes in two colours and acids change only one of them. If you dip blue litmus in lemon juice, do you expect it to stay blue or change?",
    },
    {
        "persona": "practical_encourager",
        "mode": "balanced",
        "student": "Renewable and non-renewable—are they the same thing?",
        "hint": "One kind of energy keeps arriving every day; the other is dug up and gone. Which one can run out?",
    },
    {
        "persona": "practical_encourager",
        "mode": "nudge",
        "student": "Solid liquid gas—I think I've got it.",
        "hint": "A puddle on hot pavement slowly disappears into the air. What change of state is that?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "student": "What is ammonia made up of?",
        "hint": "1. It is a small gas molecule.\n2. Two kinds of atoms are joined.\n3. One kind is hydrogen.\nWhich other atom sits in the middle?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "student": "What is sodium mainly used for?",
        "hint": "1. Think of white grains by the pepper.\n2. Your body uses this metal daily.\n3. Too much of it makes you thirsty.\nWhat kitchen crystals hold a lot of it?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "student": "Why do fish need gills?",
        "hint": "1. They stay under water all the time.\n2. You use lungs for air.\n3. Water holds a gas their blood needs.\nWhat would they run out of if that pickup stopped?",
    },
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "Why do fish need gills?",
        "hint": "Fish never come up for air the way we do. If they could not pull a gas out of the water, what would they run out of?",
    },
    {
        "persona": "analytical_coach",
        "mode": "balanced",
        "student": "Series and parallel circuits confuse me.",
        "hint": "1. One wiring has a single path.\n2. The other splits like a fork.\n3. A break on a single path stops the flow.\nIf one lamp on the single path dies, what happens to the rest?",
    },
    {
        "persona": "analytical_coach",
        "mode": "nudge",
        "student": "Density is mass over volume, right?",
        "hint": "1. Keep the amount of stuff the same.\n2. Spread it into a bigger space.\n3. Each bit of space now holds less.\nDoes density go up or down?",
    },
    {
        "persona": "curious_explorer",
        "mode": "scaffold",
        "student": "Why do living things need nutrition?",
        "hint": "Bodies keep using stuff up, like a phone using charge. What happens if nothing new is taken in?",
    },
    {
        "persona": "curious_explorer",
        "mode": "balanced",
        "student": "Acids and bases feel like opposites.",
        "hint": "They act differently on indicators, not just as opposites. If lemon juice turns an indicator one color, what might a base do?",
    },
    {
        "persona": "curious_explorer",
        "mode": "nudge",
        "student": "Refraction is when light bends.",
        "hint": "It changes speed when it enters a new material. If it goes from air into water, does it bend toward the normal or away?",
    },
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "I can't tell vertebrates from invertebrates.",
        "hint": "One group has a chain of bones down the back; the other does not. If you pressed a spider's back, would you feel that chain?",
    },
    {
        "persona": "analytical_coach",
        "mode": "balanced",
        "student": "Monocots vs dicots?",
        "hint": "1. Think of grass versus a mango leaf.\n2. One has veins like tram lines.\n3. The other looks like a spider web.\nWhich leaf matches grass?",
    },
    {
        "persona": "curious_explorer",
        "mode": "nudge",
        "student": "Sound needs a medium—I remember that.",
        "hint": "Sound needs something to travel through. If two helmets touch in space, is there still a path for the vibration?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "student": "Earth's layers are confusing.",
        "hint": "1. Think of Earth like a peach.\n2. You live on the thin outer skin.\n3. A thick juicy part sits under that skin.\nWhat do we call that thick part?",
    },
    {
        "persona": "practical_encourager",
        "mode": "nudge",
        "student": "Evaporation and boiling—same thing?",
        "hint": "One happens only at the top of the water; the other can bubble all through it. On a windy lake, which would you notice first?",
    },
    {
        "persona": "curious_explorer",
        "mode": "balanced",
        "student": "What carries oxygen in blood?",
        "hint": "Something inside red blood cells carries oxygen, not the watery plasma alone. If that part were missing, what job would fail?",
    },
    {
        "persona": "practical_encourager",
        "mode": "nudge",
        "student": "If I used a wet wooden stick to poke a live wire, what would the textbook say could happen?",
        "hint": "Dry wood usually blocks electricity, but water can make a path. If the stick is wet, can electricity still travel along it?",
    },
    {
        "persona": "practical_encourager",
        "mode": "balanced",
        "kind": "attempt",
        "student": "oxygen",
        "hint": "Yes — oxygen is right. If that gas never reached their blood, what would happen when they try to swim?",
    },
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "kind": "attempt",
        "student": "carbon dioxide",
        "hint": "Not quite — think of the gas you breathe in, not the one you breathe out. Which gas is that?",
    },
    {
        "persona": "curious_explorer",
        "mode": "balanced",
        "kind": "attempt",
        "student": "they breathe water",
        "hint": "Partly right — they take something FROM the water, not the water itself. What gas is dissolved in it?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "kind": "attempt",
        "student": "table salt",
        "hint": "Yes — table salt is right.\n1. Those white crystals are in snacks too.\n2. Extra of them makes you thirsty.\n3. Your body still uses this metal.\nWhich snack job would change if you ate a lot of them?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "kind": "attempt",
        "student": "it's a medicine",
        "hint": "Not quite — think kitchen, not a hospital.\n1. White grains sit by the pepper.\n2. You sprinkle this at meals.\n3. Too much makes you thirsty.\nWhat kitchen crystals hold a lot of it?",
    },
    {
        "persona": "curious_explorer",
        "mode": "nudge",
        "kind": "attempt",
        "student": "is it oxygen?",
        "hint": "Yes — oxygen is right. If gills could not pick that gas from water, what would the fish run out of?",
    },
]

_default_bkt: Optional[ScienceBKT] = None
_DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
_LLM_CLIENT_CACHE: Optional[tuple[Any, str]] = None
_frustration_state: dict[tuple[str, str], "FrustrationSignal"] = {}
_frustration_by_user: dict[str, "FrustrationSignal"] = {}
_last_resolved_topic_by_user: dict[str, str] = {}

# Epic 7 — frustration signal lifecycle (tone/persona only; zero BKT impact).
FRUSTRATION_DECAY_TAU_SECONDS = 600.0  # 10 minutes
FRUSTRATION_EFFECTIVE_FLOOR = 0.2
FRUSTRATION_FUSION_EXTERNAL_WEIGHT = 0.7
FRUSTRATION_FUSION_INTERNAL_WEIGHT = 0.3
FRUSTRATION_SUCCESS_CLEAR_THRESHOLD = 0.78

# Lightweight chat frustration heuristics (internal fallback).
_CHAT_FRUSTRATION_PHRASES: tuple[str, ...] = (
    r"\bi\s+don'?t\s+know\b",
    r"\bno\s+idea\b",
    r"\bi'?m\s+stuck\b",
    r"\bconfused\b",
    r"\bdon'?t\s+understand\b",
    r"\bcan'?t\s+understand\b",
    r"\bthis\s+is\s+hard\b",
    r"\btoo\s+hard\b",
    r"\bhelp\s+me\b",
    r"\bi\s+give\s+up\b",
    r"\bwhat\s+even\s+is\b",
    r"\bmake\s+no\s+sense\b",
    r"\bdoesn'?t\s+make\s+sense\b",
)

# Extra student phrasing aliases layered on top of syllabus keywords (all grades).
_STUDENT_TOPIC_ALIASES: dict[str, list[str]] = {
    "G6_C1_ORG_CHARS": [
        "living thing", "non living", "alive", "not alive", "grow", "breathe",
        "reproduce", "reproduction", "respond", "sensitive",
    ],
    "G6_C1_ORG_DIFF": [
        "heterotroph",
        "heterotrophic",
        "heterotrophs",
        "autotroph",
        "autotrophic",
        "autotrophs",
        "make their own food",
        "cannot make food",
    ],
    "G6_C10_FOO_NUTR": [
        "heterotroph",
        "heterotrophic",
        "autotroph",
        "autotrophic",
        "herbivore",
        "carnivore",
        "omnivore",
    ],
    "G7_C1_PLA_CLASSIF": ["monocot", "dicot", "monocots", "dicots"],
    "G7_C12_BIO_SYSTEMS": [
        "stomach", "digestive", "digestion", "digestive system",
        "intestine", "gut",
    ],
    "G8_C11_PHO_PROCESS": ["photosynthesis", "chlorophyll", "glucose"],
    "G9_C14_WAV_REFRACT": ["refraction", "refract", "critical angle"],
    "G7_C11_SOU_PROPAG": ["sound wave", "frequency", "amplitude", "pitch"],
    "G6_C8_ELE_CONDINS": ["conductor", "insulator", "rubber wire"],
}

# Per-student farm score key (not a curriculum skill).
USER_LEVEL_FRUSTRATION_TOPIC = "USER"


@dataclass
class FrustrationSignal:
    """Latest engagement signal used to adapt tutor tone (not BKT mastery)."""

    frustration_score: float
    level: Literal["low", "medium", "high"]
    source: str = "engagement_module"
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FrustrationResolution:
    """Resolved affective state for one tutor turn (fusion + decay applied)."""

    level: Optional[Literal["low", "medium", "high"]]
    fused_score: float
    effective_score: float
    frustration_raw: Optional[float]
    external_effective: Optional[float]
    internal_score: float
    source_tag: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_recorded_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _utc_now()


def _frustration_level_from_score(score: float) -> Literal["low", "medium", "high"]:
    s = max(0.0, min(1.0, float(score)))
    if s > 0.66:
        return "high"
    if s >= 0.34:
        return "medium"
    return "low"


def _decayed_effective_score(raw: float, recorded_at: datetime) -> float:
    """Exponential decay: effective = raw * exp(-age / tau)."""
    now = _utc_now()
    rec = _parse_recorded_at(recorded_at)
    age_sec = max(0.0, (now - rec).total_seconds())
    return max(0.0, min(1.0, float(raw))) * math.exp(-age_sec / FRUSTRATION_DECAY_TAU_SECONDS)


def score_frustration_from_chat(student_answer: str) -> float:
    """
    Lightweight internal frustration heuristic from free-text (0.0–1.0).

    Scans for confusion phrases, shouting (ALL CAPS), repeated punctuation,
    and very short baffled replies. Used when external engagement cues are
    missing or expired.
    """
    text = (student_answer or "").strip()
    if not text:
        return 0.0

    lower = text.lower()
    score = 0.0

    for pattern in _CHAT_FRUSTRATION_PHRASES:
        if re.search(pattern, lower):
            score += 0.22

    if re.search(r"\?{2,}", text):
        score += 0.18
    if re.search(r"!{2,}", text):
        score += 0.12

    letters = re.findall(r"[A-Za-z]", text)
    if len(letters) >= 8:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio >= 0.75:
            score += 0.20

    words = re.findall(r"[a-z0-9']+", lower)
    if len(words) <= 3 and ("?" in text or any(w in lower for w in ("help", "stuck", "confused"))):
        score += 0.15

    return max(0.0, min(1.0, score))


def ensure_gaming_frustration_cue(
    user_id: str,
    topic_id: str,
    *,
    session_id: Optional[str] = None,
) -> Optional["FrustrationSignal"]:
    """
    If no in-memory cue exists for this learner, pull Component 3's GET API.

    Farm frustration is per-student (not per curriculum skill), so cues are
    stored under ``USER``. Fail-open: a down gaming backend must not block tutor turns.
    """
    del topic_id  # curriculum skill is unused — farm score is user-level
    stored = _get_frustration_signal(user_id, USER_LEVEL_FRUSTRATION_TOPIC)
    if stored is not None:
        return stored
    try:
        from gaming_frustration_client import fetch_gaming_frustration

        snapshot = fetch_gaming_frustration(str(user_id), session_id=session_id)
    except Exception:
        return None
    if not snapshot:
        return None
    signal = upsert_frustration_signal(
        user_id=user_id,
        topic_id=USER_LEVEL_FRUSTRATION_TOPIC,
        frustration_score=float(snapshot["frustration_score"]),
        source=str(snapshot.get("source") or "gaming_service_get"),
    )
    try:
        from postgres_store import insert_frustration_cue

        insert_frustration_cue(
            {
                "user_id": str(user_id),
                "frustration_score": float(signal.frustration_score),
                "source": str(signal.source),
                "recorded_at": signal.recorded_at.isoformat(),
            }
        )
    except Exception:
        pass
    return signal


def upsert_frustration_signal(
    user_id: str,
    topic_id: str,
    frustration_score: float,
    *,
    source: str = "engagement_module",
    recorded_at: Optional[datetime] = None,
) -> FrustrationSignal:
    """
    Store the latest external frustration cue for a user+topic.

    ``frustration_score`` is clamped to [0, 1] and mapped to low / medium / high.
    """
    score = max(0.0, min(1.0, float(frustration_score)))
    level = _frustration_level_from_score(score)
    signal = FrustrationSignal(
        frustration_score=score,
        level=level,
        source=source,
        recorded_at=recorded_at or _utc_now(),
    )
    _frustration_state[(str(user_id), str(topic_id))] = signal
    _frustration_by_user[str(user_id)] = signal
    return signal


def _get_frustration_signal(user_id: str, topic_id: str) -> Optional[FrustrationSignal]:
    """Topic cue first; else the student's latest overall gaming score."""
    return _frustration_state.get((str(user_id), str(topic_id))) or _frustration_by_user.get(
        str(user_id)
    )


def resolve_frustration_for_turn(
    user_id: str,
    topic_id: str,
    student_answer: str,
) -> FrustrationResolution:
    """
    Fuse decayed external cue (if any) with internal chat heuristic for this turn.
    """
    internal = score_frustration_from_chat(student_answer)
    stored = _get_frustration_signal(user_id, topic_id)
    external_raw: Optional[float] = None
    external_effective: Optional[float] = None

    if stored is not None:
        external_raw = float(stored.frustration_score)
        decayed = _decayed_effective_score(external_raw, stored.recorded_at)
        if decayed >= FRUSTRATION_EFFECTIVE_FLOOR:
            external_effective = decayed

    if external_effective is not None:
        fused = (
            FRUSTRATION_FUSION_EXTERNAL_WEIGHT * external_effective
            + FRUSTRATION_FUSION_INTERNAL_WEIGHT * internal
        )
        source_tag = "fused"
    elif internal >= FRUSTRATION_EFFECTIVE_FLOOR:
        fused = internal
        source_tag = "internal_only"
    else:
        return FrustrationResolution(
            level=None,
            fused_score=0.0,
            effective_score=0.0,
            frustration_raw=external_raw,
            external_effective=external_effective,
            internal_score=internal,
            source_tag="none",
        )

    fused = max(0.0, min(1.0, fused))
    if fused < FRUSTRATION_EFFECTIVE_FLOOR:
        return FrustrationResolution(
            level=None,
            fused_score=fused,
            effective_score=fused,
            frustration_raw=external_raw,
            external_effective=external_effective,
            internal_score=internal,
            source_tag=source_tag,
        )

    return FrustrationResolution(
        level=_frustration_level_from_score(fused),
        fused_score=fused,
        effective_score=fused,
        frustration_raw=external_raw,
        external_effective=external_effective,
        internal_score=internal,
        source_tag=source_tag,
    )


def consume_frustration_after_hint(
    user_id: str,
    topic_id: str,
    interaction_score: Optional[float],
) -> None:
    """
    Post-hint lifecycle: clear on success, otherwise step down one frustration band.

    Does not touch BKT state.
    """
    uid = str(user_id)
    key = (uid, str(topic_id))
    topic_stored = _frustration_state.get(key)
    user_stored = _frustration_by_user.get(uid)
    stored = topic_stored or user_stored
    if stored is None:
        return

    if interaction_score is not None and float(interaction_score) >= FRUSTRATION_SUCCESS_CLEAR_THRESHOLD:
        next_signal = None
    elif stored.level == "high":
        next_signal = FrustrationSignal(
            frustration_score=0.50,
            level=_frustration_level_from_score(0.50),
            source=stored.source,
            recorded_at=_utc_now(),
        )
    elif stored.level == "medium":
        next_signal = FrustrationSignal(
            frustration_score=0.25,
            level=_frustration_level_from_score(0.25),
            source=stored.source,
            recorded_at=_utc_now(),
        )
    else:
        next_signal = None

    if topic_stored is not None:
        if next_signal is None:
            _frustration_state.pop(key, None)
        else:
            _frustration_state[key] = next_signal
    if user_stored is not None:
        if next_signal is None:
            _frustration_by_user.pop(uid, None)
        else:
            _frustration_by_user[uid] = next_signal


def build_frustration_audit_fields(
    resolution: FrustrationResolution,
    persona_id: str,
) -> dict[str, Any]:
    """Metadata for interaction_logs.json thesis audit pipeline."""
    return {
        "frustration_raw": resolution.frustration_raw,
        "frustration_internal_score": resolution.internal_score,
        "frustration_external_effective": resolution.external_effective,
        "effective_score": resolution.effective_score,
        "frustration_fused_score": resolution.fused_score,
        "source_tag": resolution.source_tag,
        "frustration_level_used": resolution.level,
        "persona_id_used": persona_id,
    }


def _tone_guidance_from_frustration(resolution: FrustrationResolution) -> str:
    if resolution.level is None:
        return (
            "No active frustration signal for this turn (decayed/expired or calm chat). "
            "Keep your normal warm, concise Socratic tone."
        )
    if resolution.level == "high":
        return (
            "Frustration signal is HIGH — apply these tone rules even where they relax the "
            "usual correction-first *shape* (still be curriculum-accurate and Socratic, no full solutions):\n"
            "- Open with brief reassurance or empathy for confusion; normalize not knowing.\n"
            "- Do NOT open by quoting the student only to contrast or contradict (avoid "
            "'You said \"...\", but...' / 'You said X, but earlier...').\n"
            "- Do not stack reminders about past mistakes or prior turns; one gentle fix, then move on.\n"
            "- Use short sentences; one small idea; exactly ONE very easy next-step or yes/no question.\n"
            "- If they say 'I don't know' / 'no idea', answer with warmth first—never imply they should "
            "already know the answer."
        )
    if resolution.level == "medium":
        return (
            "Frustration signal is MEDIUM. Be supportive. Short sentences, no jargon, "
            "one idea, exactly ONE easy question."
        )
    return (
        "Frustration signal is LOW. Stay warm and very short. Still one idea and one question."
    )


def _get_default_bkt() -> ScienceBKT:
    global _default_bkt
    if _default_bkt is None:
        _default_bkt = ScienceBKT(
            params_source="postgres",
            persist_mastery=True,
        )
        _default_bkt.initialize_skills()
    return _default_bkt


def get_shared_bkt_engine() -> ScienceBKT:
    """
    Shared ``ScienceBKT`` used by tutor hints and the assessment API.

    Keeps one ``predict_update`` / ``student_state`` path per ``(user_id, skill)``.
    """
    return _get_default_bkt()


def _make_llm_client() -> tuple[Any, str]:
    """Return (ChatGroq client, model_name). Reuses one client per process."""
    global _LLM_CLIENT_CACHE
    _load_env()
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it to your .env file."
        )
    model = (
        os.environ.get("GROQ_MODEL_NAME", _DEFAULT_GROQ_MODEL).strip()
        or _DEFAULT_GROQ_MODEL
    )
    if _LLM_CLIENT_CACHE is not None:
        cached_client, cached_model = _LLM_CLIENT_CACHE
        if cached_model == model:
            return cached_client, cached_model
    temp_raw = os.environ.get("TUTOR_LLM_TEMPERATURE", "").strip()
    temperature = 0.35
    if temp_raw:
        try:
            temperature = float(temp_raw)
        except ValueError:
            temperature = 0.35
    temperature = max(0.0, min(1.5, temperature))
    client_kwargs: dict[str, Any] = {
        "model_name": model,
        "api_key": api_key,
        "temperature": temperature,
    }
    # GPT-OSS models are reasoning models: without a low effort setting they
    # can consume the entire token budget on hidden reasoning and return empty
    # visible content (finish_reason=length), which breaks JSON hint parsing.
    if "gpt-oss" in model.lower():
        client_kwargs["reasoning_effort"] = "low"
    client = ChatGroq(**client_kwargs)
    _LLM_CLIENT_CACHE = (client, model)
    return client, model


def _llm_response_text(content: Any) -> str:
    """Normalize LangChain message content to a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(block, "text", None) or getattr(block, "content", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return str(content).strip()


def _tutor_llm_max_tokens() -> int:
    raw = os.environ.get("TUTOR_LLM_MAX_TOKENS", "512").strip()
    try:
        return max(256, min(1024, int(raw)))
    except ValueError:
        return 512


def _tutor_bkt_policy() -> Literal["quiz_only", "strict", "legacy"]:
    """How chat turns update BKT; default ``quiz_only`` so only assessments change mastery."""
    _load_env()
    raw = (os.environ.get("TUTOR_BKT_POLICY") or "quiz_only").strip().lower()
    if raw in {"quiz_only", "quiz-only", "off", "false", "0", "none", "assessment_only"}:
        return "quiz_only"
    if raw in {"legacy", "lenient", "old"}:
        return "legacy"
    return "strict"


def _dialogue_score_to_bkt_label(score: float) -> tuple[Optional[int], Optional[str]]:
    """
    Map model ``interaction_score`` to a binary BKT label or skip.

    ``strict``: clear correct / incorrect only; ambiguous mid-range → no ``predict_update``.
    ``quiz_only``: never update from dialogue (return ``None``, note reason).
    ``legacy``: historical lenient threshold (often inflates mastery).
    """
    policy = _tutor_bkt_policy()
    sc = max(0.0, min(1.0, float(score)))

    if policy == "quiz_only":
        return None, "quiz_only_tutor_skipped_bkt_use_assessment_endpoint"

    if policy == "legacy":
        lbl = _socratic_discounted_bkt_label(sc)
        return lbl, None

    if sc >= 0.78:
        return 1, None
    if sc <= 0.42:
        return 0, None
    return None, "dialogue_score_ambiguous_bkt_skipped"


def _format_conversation_history(
    turns: Optional[list[dict[str, Any]]],
    *,
    max_turns: int = 10,
    max_chars_per_turn: int = 1200,
) -> str:
    if not turns:
        return ""
    lines: list[str] = []
    for t in turns[-max_turns:]:
        if not isinstance(t, dict):
            continue
        role = str(t.get("role") or "").strip().lower()
        content = str(t.get("content") or "").strip()
        if not content:
            continue
        if role not in ("user", "assistant"):
            continue
        label = (
            "Student (learner said this)"
            if role == "user"
            else "Tutor (YOU said this earlier — not the student's idea)"
        )
        lines.append(f"{label}: {content[:max_chars_per_turn]}")
    return "\n".join(lines)


def _hint_mode(mastery: float) -> HintMode:
    if mastery < 0.5:
        return "scaffold"
    if mastery > 0.8:
        return "nudge"
    return "balanced"


# Phrases that signal wrap-up / gratitude (not a new science attempt).
_ACKNOWLEDGMENT_PATTERN = re.compile(
    r"(?:"
    r"\bthanks?\b|\bthank\s+you\b|\bthx\b|\bty\b|"
    r"\bi\s+(?:get|got|understand)\s+(?:it|that|this)(?:\s+now)?\b|"
    r"\bi\s+understood\b|\bunderstood\b|"
    r"\bthat\s+makes\s+sense\b|\bmakes\s+sense\b|"
    r"\bgot\s+it\b|\ball\s+clear\b|\bthat(?:'s| is)\s+clear\b|"
    r"\bmuch\s+clearer\b|\bcrystal\s+clear\b|"
    r"\bthat\s+helps?\b|\bthat(?:'s| is)\s+helpful\b|"
    r"\bi(?:'m|\s+am)\s+(?:good|all\s+set|done)\b|"
    r"\bno\s+more\s+questions?\b|\bthat(?:'s| is)\s+all\b|"
    r"\bi\s+appreciate\s+(?:it|that)\b"
    r")",
    re.IGNORECASE,
)

# Residual tokens that suggest the student is still asking about science.
_ACK_RESIDUAL_SCIENCE_HINT = re.compile(
    r"\b(?:"
    r"what|why|how|when|where|which|explain|difference|between|mean|means|"
    r"conductor|insulator|circuit|energy|force|cell|atom|plant|animal|"
    r"light|sound|heat|acid|base|density|photosynthesis|current|voltage|"
    r"solid|liquid|gas|evaporat|boil|refract|lens"
    r")\b",
    re.IGNORECASE,
)

_ACKNOWLEDGMENT_CLOSURES: dict[str, str] = {
    "practical_encourager": (
        "Glad that clicked for you—you've built a solid everyday feel for this idea. "
        "Whenever you're ready for the next concept, just ask."
    ),
    "analytical_coach": (
        "Excellent synthesis—you've locked in the foundational logic for this mechanism. "
        "Let me know when you're ready to break down the next concept."
    ),
    "curious_explorer": (
        "Nice—you've cracked this piece of the puzzle. "
        "Whenever curiosity pulls you toward the next mystery, I'm here."
    ),
}

# Opening greetings (new chat "Hi") — not science questions and not wrap-up thanks.
_GREETING_PATTERN = re.compile(
    r"^(?:"
    r"(?:hi+|hello+|hey+|heya+|hiya+|howdy+|yo)"
    r"(?:\s+(?:there|again|tutor|teacher|bot|everyone))?"
    r"|"
    r"good\s+(?:morning|afternoon|evening|day)"
    r"|"
    r"how\s+are\s+you(?:\s+doing)?"
    r"|"
    r"how(?:'s|s|\s+is)\s+it\s+going"
    r"|"
    r"what(?:'s|s|\s+is)\s+up"
    r")[\s!.?,]*$",
    re.IGNORECASE,
)

_GREETING_OPENERS: dict[str, str] = {
    "practical_encourager": (
        "Hi! I'm your science tutor for Grades 6–9. "
        "How can I help you today — what topic would you like to work on?"
    ),
    "analytical_coach": (
        "Hello. I help you figure out Grade 6–9 science by asking questions, not by "
        "handing over the answer. Which topic should we start with?"
    ),
    "curious_explorer": (
        "Hey! I can investigate a Grade 6–9 science idea with you. "
        "What topic should we start with?"
    ),
}


_HELP_INTENT_RE = re.compile(
    r"^(?:"
    r"(?:please\s+)?(?:give|show|tell)\s+me\s+(?:a\s+)?hint|"
    r"hint(?:\s+please)?|"
    r"(?:can|could|may)\s+i\s+(?:have|get)\s+(?:a\s+)?hint|"
    r"i\s+need\s+(?:a\s+)?hint|"
    r"(?:i['’]?m\s+|i\s+am\s+)?(?:so\s+|really\s+|still\s+)?"
    r"(?:stuck|confused|lost)(?:\s+on this(?: step)?)?|"
    r"help(?:\s+me)?(?:\s+please)?|"
    r"idk|"
    r"i\s+don['’]?t\s+(?:know|get|understand)(?:\s+it|\s+this)?"
    r")[\s!.?…]*$",
    re.IGNORECASE,
)


def _plain_student_text(text: str) -> str:
    stripped = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text or "")
    return re.sub(r"\s+", " ", stripped).strip()


def _is_help_intent(student_answer: str) -> bool:
    """True for hint / stuck / idk chips with no extra science content."""
    plain = _plain_student_text(student_answer)
    if not plain:
        return False
    return bool(_HELP_INTENT_RE.match(plain))


_ANSWER_SEEKING_RE = re.compile(
    r"(?:"
    r"\bwhy\b|"
    r"\bwhat\s+(?:is|are|does|do|did|happens|happened|makes|causes|would|can|could)\b|"
    r"\bwhat'?s\b|"
    r"\bhow\s+(?:do|does|did|can|could|would|should|to|is|are|come)\b|"
    r"\bwhen\s+(?:do|does|did|is|are|can|would)\b|"
    r"\bwhere\s+(?:do|does|did|is|are|can)\b|"
    r"\bwhich\s+(?:one|ones|is|are|do|does)\b|"
    r"\bwho\s+(?:do|does|is|are)\b|"
    r"\bdefine\b|\bidentify\b|\bexplain\b|\bdescribe\b|"
    r"\btell\s+me\b|"
    r"\bmade\s+(?:up\s+)?of\b|\bcomposed\s+of\b|"
    r"\bused\s+for\b|\bmainly\s+used\b|"
    r"\bfunction\s+of\b|\bpurpose\s+of\b|"
    r"\bdifference\s+between\b|"
    r"\bcan\s+you\s+(?:explain|tell|say|teach|show)\b|"
    r"\b(?:do|does|did)\s+\w+\s+need\b"
    r")",
    re.IGNORECASE,
)

_HYPOTHESIS_RE = re.compile(
    r"^\s*(?:is\s+it(?:\s+because)?|is\s+that|could\s+it(?:\s+be)?|maybe|perhaps|"
    r"i\s+think|does\s+that\s+mean|so\s+is\s+it|am\s+i\s+right)",
    re.IGNORECASE,
)


def _is_answer_seeking_intent(student_answer: str) -> bool:
    """True when they asked to be taught the fact, not when they offered an attempt."""
    if _is_help_intent(student_answer):
        return False
    plain = _plain_student_text(student_answer)
    if not plain:
        return False
    if _HYPOTHESIS_RE.search(plain):
        return False
    if _ANSWER_SEEKING_RE.search(plain):
        return True
    return "?" in plain


_STRONG_QUESTION_RE = re.compile(
    r"\b(?:why|what|how|explain|define|describe|tell me|used for|"
    r"function of|purpose of|difference between)\b",
    re.IGNORECASE,
)


def _is_attempt_intent(student_answer: str, last_follow_up: str) -> bool:
    """True when they replied to the previous tutor question with an answer or guess."""
    if not (last_follow_up or "").strip():
        return False
    if _is_help_intent(student_answer):
        return False
    plain = _plain_student_text(student_answer)
    if not plain:
        return False
    if _HYPOTHESIS_RE.search(plain):
        return True
    if _STRONG_QUESTION_RE.search(plain) and (
        "?" in plain or _ANSWER_SEEKING_RE.search(plain)
    ):
        return False
    return True


def _last_tutor_follow_up(turns: Optional[list[dict[str, Any]]]) -> str:
    """The previous tutor question the learner is stuck on."""
    if not turns:
        return ""
    for turn in reversed(turns):
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role") or "").strip().lower() != "assistant":
            continue
        content = str(turn.get("content") or "").strip()
        if not content:
            continue
        match = re.search(r"([^\n?]+\?)\s*$", content)
        if match:
            return match.group(1).strip()
        return content[-240:]
    return ""


def _is_greeting_intent(student_answer: str) -> bool:
    """True for short standalone greetings like Hi / Hello, not science questions."""
    text = (student_answer or "").strip()
    if not text:
        return False
    words = re.findall(r"[a-z0-9']+", text.lower())
    if not words or len(words) > 8:
        return False
    if "?" in text and not _GREETING_PATTERN.fullmatch(text.strip()):
        # "Hi, what is a conductor?" is a real question.
        residual = _GREETING_PATTERN.sub(" ", text.lower())
        if _ACK_RESIDUAL_SCIENCE_HINT.search(residual):
            return False
    return bool(_GREETING_PATTERN.fullmatch(text.strip()))


def _is_acknowledgment_intent(student_answer: str) -> bool:
    """
    Lightweight pre-routing gate: detect gratitude / wrap-up / \"I get it\" messages.

    Returns True only when the message is primarily acknowledgment—not a new science
    question or substantive attempt that happens to include a polite word.
    """
    text = (student_answer or "").strip()
    if not text:
        return False

    lower = text.lower()
    words = re.findall(r"[a-z0-9']+", lower)
    if not words or len(words) > 20:
        return False

    if not _ACKNOWLEDGMENT_PATTERN.search(lower):
        return False

    # Strip acknowledgment / filler phrases; leftover science or questions → continue tutoring.
    residual = _ACKNOWLEDGMENT_PATTERN.sub(" ", lower)
    residual = re.sub(
        r"\b(?:"
        r"great|ok|okay|alright|all\s+right|cool|nice|awesome|perfect|"
        r"yes|yeah|yep|yup|sure|now|well|really|so|just|then|"
        r"i|you|it|that|this|a|an|the|and|but|for|to|of|my|me"
        r")\b",
        " ",
        residual,
        flags=re.IGNORECASE,
    )
    residual = re.sub(r"[^\w\s]", " ", residual)
    residual_words = re.findall(r"[a-z0-9']+", residual.lower())

    if residual_words and _ACK_RESIDUAL_SCIENCE_HINT.search(" ".join(residual_words)):
        return False
    if residual_words and len(residual_words) >= 4:
        return False
    # "thanks, what about series?" style — leftover after strip still asks something.
    if "?" in text and residual_words:
        return False
    return True


def _acknowledgment_closure_response(
    *,
    user_id: str,
    topic_id: str,
    persona_id: Optional[str],
    student_answer: str = "",
    bkt: Optional[ScienceBKT] = None,
    topic_id_inferred: bool = False,
    topic_changed: bool = False,
) -> dict[str, Any]:
    """Persona-matched closing reply; skips RAG, LLM Socratic loop, and BKT updates."""
    engine = bkt or _get_default_bkt()
    mastery = float(engine.get_current_mastery_probability(user_id, topic_id))
    frustration_resolution = resolve_frustration_for_turn(
        user_id, topic_id, student_answer
    )
    resolved_persona = _resolve_persona_id(
        persona_id,
        user_id,
        frustration_level=frustration_resolution.level,
    )
    persona_label = _PERSONA_LABELS[resolved_persona]
    hint_text = _ACKNOWLEDGMENT_CLOSURES[resolved_persona]
    frustration_audit = build_frustration_audit_fields(
        frustration_resolution, resolved_persona
    )
    return {
        "success": True,
        "user_id": str(user_id),
        "topic_id": str(topic_id),
        "mastery_probability": mastery,
        "mastery_probability_before": mastery,
        "updated_mastery_probability": mastery,
        "hint_mode": _hint_mode(mastery),
        "persona_id": resolved_persona,
        "persona_label": persona_label,
        "hint_text": hint_text,
        "interaction_score": None,
        "interaction_score_effective": None,
        "bkt_updated": False,
        "bkt_observation_label": None,
        "tutor_bkt_policy": _tutor_bkt_policy(),
        "bkt_update_note": "acknowledgment_intent_closure_no_bkt",
        "risk_flag": False,
        "retrieval": {
            "chunks_returned": 0,
            "query_used": None,
            "skipped": True,
            "skip_reason": "acknowledgment_intent",
        },
        "frustration_level_used": frustration_resolution.level,
        "frustration_score_used": frustration_resolution.effective_score,
        **frustration_audit,
        "llm_model": None,
        "conversation_intent": "acknowledgment",
        "socratic_loop_bypassed": True,
        "topic_id_inferred": topic_id_inferred,
        "topic_id_resolved": str(topic_id),
        "topic_changed": topic_changed,
        "history_turns_sent": 0,
    }


def _greeting_opener_response(
    *,
    user_id: str,
    persona_id: Optional[str],
    student_answer: str = "",
    topic_id: Optional[str] = None,
    bkt: Optional[ScienceBKT] = None,
) -> dict[str, Any]:
    """Invite the student to name a science topic; skip RAG / LLM / BKT / topic routing."""
    sticky_topic = (
        topic_id
        or _last_resolved_topic_by_user.get(str(user_id))
        or FALLBACK_TOPIC_ID
    )
    frustration_resolution = resolve_frustration_for_turn(
        user_id, sticky_topic, student_answer
    )
    resolved_persona = _resolve_persona_id(
        persona_id,
        user_id,
        frustration_level=frustration_resolution.level,
    )
    persona_label = _PERSONA_LABELS[resolved_persona]
    frustration_audit = build_frustration_audit_fields(
        frustration_resolution, resolved_persona
    )
    return {
        "success": True,
        "user_id": str(user_id),
        "topic_id": None,
        "mastery_probability": None,
        "mastery_probability_before": None,
        "updated_mastery_probability": None,
        "hint_mode": None,
        "persona_id": resolved_persona,
        "persona_label": persona_label,
        "hint_text": _GREETING_OPENERS.get(
            resolved_persona,
            _GREETING_OPENERS["practical_encourager"],
        ),
        "interaction_score": None,
        "interaction_score_effective": None,
        "bkt_updated": False,
        "bkt_observation_label": None,
        "tutor_bkt_policy": _tutor_bkt_policy(),
        "bkt_update_note": "greeting_intent_opener_no_bkt",
        "risk_flag": False,
        "retrieval": {
            "chunks_returned": 0,
            "query_used": None,
            "skipped": True,
            "skip_reason": "greeting_intent",
        },
        "frustration_level_used": frustration_resolution.level,
        "frustration_score_used": frustration_resolution.effective_score,
        **frustration_audit,
        "llm_model": None,
        "conversation_intent": "greeting",
        "socratic_loop_bypassed": True,
        "topic_id_inferred": False,
        "topic_id_resolved": None,
        "topic_changed": False,
        "history_turns_sent": 0,
    }


def _resolve_persona_id(
    persona_id: Optional[str],
    user_id: str,
    *,
    frustration_level: Optional[Literal["low", "medium", "high"]] = None,
) -> str:
    """
    Resolve active persona for this turn.

    Priority: high frustration (Practical Encourager) → client ``persona_id`` →
    ``TUTOR_DEFAULT_PERSONA`` env → random rotation.
    """
    if frustration_level == "high":
        return "practical_encourager"

    if persona_id:
        normalized = persona_id.strip().lower().replace("-", "_").replace(" ", "_")
        resolved = _PERSONA_ALIASES.get(normalized)
        if resolved:
            return resolved

    env_default = (os.environ.get("TUTOR_DEFAULT_PERSONA") or "").strip().lower()
    if env_default:
        env_norm = env_default.replace("-", "_").replace(" ", "_")
        resolved = _PERSONA_ALIASES.get(env_norm)
        if resolved:
            return resolved

    _ = user_id  # reserved for future per-learner rotation policies
    return random.choice(list(_VALID_PERSONAS))


def _format_few_shot_examples(
    persona: str,
    mode: HintMode,
    *,
    max_examples: int = 3,
    help_intent: bool = False,
    answer_seeking: bool = False,
    attempt: bool = False,
) -> str:
    """Compile few-shot demonstrations with emphasis on the active persona × mode."""
    ranked: list[tuple[int, int, dict[str, str]]] = []
    for idx, example in enumerate(_FEW_SHOT_EXAMPLES):
        score = 0
        if example["persona"] == persona:
            score += 3
        if example["mode"] == mode:
            score += 3
        if example["persona"] == persona and example["mode"] == mode:
            score += 2
        if help_intent and _is_help_intent(example["student"]):
            score += 6
        elif not help_intent and _is_help_intent(example["student"]):
            score -= 4
        if answer_seeking and _is_answer_seeking_intent(example["student"]):
            score += 6
        elif attempt and example.get("kind") == "attempt":
            score += 8
        elif not attempt and example.get("kind") == "attempt":
            score -= 4
        elif attempt and _is_answer_seeking_intent(example["student"]):
            score -= 4
        ranked.append((score, idx, example))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    lines: list[str] = []
    for _, _, example in ranked[:max_examples]:
        label = _PERSONA_LABELS[example["persona"]]
        lines.append(
            f"[{label} · {example['mode'].upper()}]\n"
            f"Student: {example['student']}\n"
            f"Tutor hint_text: {example['hint']}"
        )
    return "\n\n".join(lines)


def _build_system_prompt(
    mode: HintMode,
    persona: str,
    tone_guidance: str,
    *,
    help_intent: bool = False,
    answer_seeking: bool = False,
    attempt: bool = False,
) -> str:
    persona_label = _PERSONA_LABELS[persona]
    state_config = _PERSONA_STATE_MATRIX[persona][mode]
    few_shots = _format_few_shot_examples(
        persona,
        mode,
        help_intent=help_intent,
        answer_seeking=answer_seeking,
        attempt=attempt,
    )

    help_block = ""
    if answer_seeking:
        help_block = (
            "--- ANSWER-SEEKING TURN (mandatory) ---\n"
            "The student asked a science question (why / what / how / need / used for / …). "
            "Do NOT write the answer. No function, no colour-change rule, no formula, no uses list. "
            "Analytical Coach: 3 numbered riddles a marker could NOT tick, then one question.\n"
            "BAD: \"Fish use gills to take oxygen from water.\"\n"
            "BAD: \"1. Sodium is in table salt 2. nerves 3. fluids\"\n"
            "GOOD: \"Fish stay underwater and cannot use lungs like you. What gas in the "
            "water must reach their blood?\"\n\n"
        )
    elif help_intent:
        help_block = (
            "--- HELP TURN (mandatory) ---\n"
            "The latest student message is a plea for help (hint / stuck / I don't know). "
            "It is NOT a science answer and NOT agreement with your last idea.\n"
            "They are stuck on YOUR previous follow-up question.\n"
            "Give one smaller clue toward THAT question. Then ask a simpler version of it.\n"
            "NEVER write 'you thought', 'you mentioned', 'you said', or 'you picked' unless "
            "those words appear on a Student line. Tutor lines are your own previous words.\n\n"
        )
    elif attempt:
        help_block = (
            "--- ATTEMPT TURN (mandatory) ---\n"
            "The latest student message answers YOUR previous follow-up. It is an attempt, "
            "not a new request to be taught.\n"
            "Sentence 1 MUST be a verdict, before any new clue or question:\n"
            "- Correct: \"Yes — that's right.\" (you may echo 2–4 of their words)\n"
            "- Wrong: \"Not quite.\" Then a smaller clue. Do NOT then state the correct fact.\n"
            "- Partial: \"Partly right — you got [their correct bit].\"\n"
            "Only AFTER the verdict: one next Socratic step and ONE new question.\n"
            "Analytical Coach: verdict on its own first line, then 3 numbered clues, then the question.\n"
            "NEVER skip the verdict and jump to a new topic.\n\n"
        )
    else:
        help_block = (
            "--- Attribution ---\n"
            "Only echo words from Student lines. Never treat a Tutor line as something "
            "the learner thought or said.\n\n"
        )

    return (
        f"You are **{persona_label}**, a Grade 6–9 SOCRATIC science tutor. "
        f"Students learn by answering YOUR question. You never hand them the finished fact. "
        f"Keep every reply short enough to read in one glance.\n"
        f"Active state: persona_id={persona}, hint_mode={mode}.\n"
        f"Private curriculum notes in the user message are for YOUR eyes only. Coach in your "
        f"own simple voice. Never call them \"text\", \"excerpts\", or \"the textbook\". "
        f"If the student is wrong, redirect in plain words—not citations.\n\n"
        f"{_SOCRATIC_GUARDRAILS}\n\n"
        f"--- Active persona × mastery configuration ---\n"
        f"{state_config}\n\n"
        f"{help_block}"
        f"--- Conversational continuity ---\n"
        f"- THREAD: If they answered your last question, verdict first (right / not quite / partly), "
        f"then one next clue. Never skip the verdict.\n"
        f"- MEMORY: Echo at most 2–4 words from a Student line only.\n"
        f"- FIGURES / LABELS: Do not mention figures, diagrams, exercises, tables, or pages.\n"
        f"- SENTIMENT ADAPTATION: {tone_guidance}\n"
        f"  High frustration: even shorter, even kinder, still one idea.\n\n"
        f"{_correction_protocol(persona, answer_seeking=answer_seeking, attempt=attempt)}"
        f"--- Few-shot length/voice samples (copy LENGTH, not facts) ---\n"
        f"{few_shots}\n\n"
        f"--- interaction_score (JSON field only; never shown in hint_text) ---\n"
        f"Set \"interaction_score\" from 0.0 to 1.0 for how well their **latest** answer matches "
        f"correct science per your private curriculum notes. Be calibrated: wrong/vague usually "
        f"≤0.35; major misconception ≤0.25; only clearly correct ≥0.78.\n"
        f"  • 0.0–0.35: wrong, vague, or major misconception\n"
        f"  • 0.36–0.77: partial / uncertain (not mastered)\n"
        f"  • 0.78–1.0: clearly correct and curriculum-aligned\n\n"
        f"{_output_format_block(persona, answer_seeking=answer_seeking, attempt=attempt)}"
    )


def _correction_protocol(
    persona: str, *, answer_seeking: bool = False, attempt: bool = False
) -> str:
    if answer_seeking:
        return (
            "--- Correction-first protocol (answer-seeking) ---\n"
            "They asked a science question. Do not answer it. Clues / riddles only, "
            "then one prediction question.\n\n"
        )
    if attempt:
        if persona == "analytical_coach":
            return (
                "--- Correction-first protocol (attempt · Analytical Coach) ---\n"
                "Line 1 (not numbered): Yes that's right / Not quite / Partly right.\n"
                "Then 3 numbered clues for the NEXT small step (or a smaller version of "
                "the same question if they were wrong). End with one question.\n"
                "If wrong, do not write the correct fact in the 3 lines.\n\n"
            )
        return (
            "--- Correction-first protocol (attempt) ---\n"
            "Sentence 1 is the verdict. Sentence 2 is one clue. Then one question. "
            "If they are right: confirm their words, then the next small step.\n"
            "If they are wrong: say not quite, contrast, ask again — do not dump the answer.\n\n"
        )
    if persona == "analytical_coach":
        return (
            "--- Correction-first protocol (Analytical Coach) ---\n"
            "Put the gentle correction inside the 3 numbered steps. Do not add a paragraph "
            "before the list. End with one question.\n\n"
        )
    return (
        "--- Correction-first protocol (still brief) ---\n"
        "If they are wrong: one kind clause + one contrast + one question. That is the whole reply.\n"
        "If they are right: one short nod + one next-step question. Do not add a mini-lesson.\n\n"
    )


def _output_format_block(
    persona: str, *, answer_seeking: bool = False, attempt: bool = False
) -> str:
    if persona == "analytical_coach":
        if attempt:
            example = (
                '{"hint_text":"Yes — table salt is right.\\n'
                '1. Those white crystals are in snacks too.\\n'
                '2. Extra of them makes you thirsty.\\n'
                '3. Your body still uses this metal.\\n'
                'Which snack job would change if you ate a lot of them?","interaction_score":0.82}'
            )
            shape = (
                "hint_text for Analytical Coach on an ATTEMPT:\n"
                "Short verdict line\n1. short clue\n2. short clue\n3. short clue\nOne short question?\n"
            )
        elif answer_seeking:
            example = (
                '{"hint_text":"1. Think of white grains by the pepper.\\n'
                '2. Your body uses this metal daily.\\n'
                '3. Too much of it makes you thirsty.\\n'
                'What kitchen crystals hold a lot of it?","interaction_score":0.28}'
            )
            shape = (
                "hint_text for Analytical Coach MUST look like 3 numbered RIDDLES (not answer facts):\n"
                "1. short clue\n2. short clue\n3. short clue\nOne short question?\n"
            )
        else:
            example = (
                '{"hint_text":"1. Think of white grains by the pepper.\\n'
                '2. Your body uses this metal daily.\\n'
                '3. Too much of it makes you thirsty.\\n'
                'What kitchen crystals hold a lot of it?","interaction_score":0.35}'
            )
            shape = (
                "hint_text for Analytical Coach MUST look like 3 numbered RIDDLES (not answer facts):\n"
                "1. short clue\n2. short clue\n3. short clue\nOne short question?\n"
            )
        return (
            "--- OUTPUT FORMAT (mandatory) ---\n"
            "Return ONLY a single JSON object with \"hint_text\" and \"interaction_score\".\n"
            f"{shape}"
            "Do NOT write uses, definitions, or identification rules in the 3 lines.\n"
            f"Example: {example}\n"
            "If interaction_score is missing or not a number, the server skips dialogue-derived "
            "BKT logic for this turn—always include a valid number.\n"
        )
    if attempt:
        return (
            "--- OUTPUT FORMAT (mandatory) ---\n"
            "Return ONLY a single JSON object with exactly two keys: \"hint_text\" (string, "
            "verdict + one clue + one question, ≤50 words) and \"interaction_score\" (number). "
            'Example: {"hint_text":"Yes — oxygen is right. If that gas never reached their blood, '
            'what would happen when they try to swim?","interaction_score":0.84}\n'
            "If interaction_score is missing or not a number, the server skips dialogue-derived "
            "BKT logic for this turn—always include a valid number.\n"
        )
    return (
        "--- OUTPUT FORMAT (mandatory) ---\n"
        "Return ONLY a single JSON object with exactly two keys: \"hint_text\" (string, "
        "1–2 short sentences + one question, ≤50 words) and \"interaction_score\" (number). "
        'Example: {"hint_text":"You already meet this metal at meals. What white crystals '
        'next to pepper hold a lot of it?","interaction_score":0.35}\n'
        "If interaction_score is missing or not a number, the server skips dialogue-derived "
        "BKT logic for this turn—always include a valid number.\n"
    )


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _parse_llm_json_payload(content: str) -> tuple[str, Optional[float], Optional[str]]:
    """
    Parse model output into (hint_text, interaction_score, error_message).

    On failure, returns (raw_or_fallback_text, None, error).
    """
    raw = (content or "").strip()
    if not raw:
        return "", None, "empty_model_response"

    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        return raw, None, f"json_decode_error:{exc}"

    if not isinstance(data, dict):
        return raw, None, "json_not_object"

    hint = data.get("hint_text")
    score = data.get("interaction_score")
    if not isinstance(hint, str) or not hint.strip():
        return raw, None, "missing_or_invalid_hint_text"
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        return hint.strip(), None, "missing_or_invalid_interaction_score"

    score_f = max(0.0, min(1.0, score_f))
    return hint.strip(), score_f, None


_NUMBERED_LINE_RE = re.compile(
    r"^\s*(?:\(?([1-9])\)?[.)]|[-*])\s+(.+?)\s*$"
)
_INLINE_STEP_RE = re.compile(
    r"(?:^|\s)\(?([1-3])\)?[.)]\s+(.+?)(?=(?:\s*\(?[1-3]\)?[.)])|$)",
    re.DOTALL,
)


def _reply_constraints(
    persona: str, *, answer_seeking: bool = False, attempt: bool = False
) -> str:
    socratic = (
        " NEVER state the finished science fact "
        "(no 'fish use gills to take oxygen from water', no uses lists, no colour-change rules)."
    )
    extra = (
        " The 3 lines must be riddles, NOT the why/what/how they asked for."
        if answer_seeking and persona == "analytical_coach"
        else (
            " Do not state the fact they asked for."
            if answer_seeking
            else (
                " First sentence MUST be Yes that's right / Not quite / Partly right. "
                "Then one next clue. Do not skip the verdict. If wrong, do not dump the correct fact."
                if attempt
                else ""
            )
        )
    )
    if persona == "analytical_coach":
        lead = (
            "Reply constraints: Analytical Coach. First line is a short verdict, then "
            "exactly 3 numbered clues (`1.` `2.` `3.`), each ≤12 Grade 6–9 words, "
            "then ONE short question on the last line."
            if attempt
            else (
                "Reply constraints: Analytical Coach. Exactly 3 numbered clues (`1.` `2.` `3.`), "
                "each ≤12 Grade 6–9 words, then ONE short question on the last line."
            )
        )
        return f"{lead}{socratic}{extra}\n"
    if attempt:
        return (
            "Reply constraints: Grade 6–9 reading level. Verdict + one clue + one question. "
            f"Max 50 words. No lists.{socratic}{extra}\n"
        )
    return (
        "Reply constraints: Grade 6–9 reading level. 1–2 short sentences + one question. "
        f"Max 50 words. No lists.{socratic}{extra}\n"
    )


def extract_analytical_steps(hint_text: str) -> tuple[list[str], Optional[str]]:
    """Split Analytical Coach hint_text into up to 3 steps plus a closing question."""
    raw = (hint_text or "").strip()
    if not raw:
        return [], None

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    steps: list[str] = []
    other: list[str] = []
    for line in lines:
        match = _NUMBERED_LINE_RE.match(line)
        if match:
            steps.append(match.group(2).strip())
        else:
            other.append(line)

    if len(steps) < 2:
        inline = _INLINE_STEP_RE.findall(re.sub(r"\s+", " ", raw))
        if len(inline) >= 2:
            steps = [chunk.strip(" .") for _, chunk in inline[:3]]
            other = []

    question: Optional[str] = None
    if other:
        question = other[-1].strip()
    elif steps and steps[-1].endswith("?"):
        question = steps.pop()

    cleaned = [
        re.sub(r"\?+", "", step).strip(" .") for step in steps if step
    ][:3]
    if question:
        q_parts = re.findall(r"[^?]*\?", question)
        question = q_parts[-1].strip() if q_parts else question
        if question.count("?") > 1:
            question = question[question.rfind("?", 0, -1) + 1 :].strip() or question
        if not question.endswith("?"):
            question = f"{question.rstrip(' .')}?"
    return cleaned, question or None


def enforce_single_follow_up_question(hint_text: str) -> str:
    """Keep at most one '?' in a tutor reply (the last follow-up)."""
    raw = (hint_text or "").strip()
    if not raw or raw.count("?") <= 1:
        return raw

    newline = "\n" in raw
    pieces = [ln.strip() for ln in raw.splitlines() if ln.strip()] if newline else [raw]

    body: list[str] = []
    questions: list[str] = []
    step_questions: list[str] = []

    for piece in pieces:
        numbered = bool(_NUMBERED_LINE_RE.match(piece))
        if numbered:
            if "?" in piece:
                match = _NUMBERED_LINE_RE.match(piece)
                if match:
                    step_questions.append(match.group(2).strip().rstrip("?").strip())
                body.append(re.sub(r"\?+", ".", piece).replace("..", ".").rstrip())
            else:
                body.append(piece)
            continue
        if "?" not in piece:
            body.append(piece)
            continue
        for segment in re.findall(r"[^?]+(?:\?|$)", piece):
            segment = segment.strip()
            if not segment:
                continue
            if segment.endswith("?"):
                questions.append(segment)
            else:
                body.append(segment.rstrip(" ,;"))

    last_q = questions[-1].strip() if questions else None
    if not last_q and step_questions:
        last_q = step_questions[-1]
    if last_q and not last_q.endswith("?"):
        last_q = f"{last_q.rstrip(' .')}?"

    sep = "\n" if newline else " "
    if body and last_q:
        return f"{sep.join(body)}{sep}{last_q}".strip()
    if last_q:
        return last_q
    return sep.join(body).strip() or raw


def _socratic_discounted_bkt_label(interaction_score: float) -> int:
    """
    Map ``interaction_score`` in [0, 1] to a binary BKT observation.

    Applies the Socratic discount: ``discounted = interaction_score * 0.5`` so help
    from the tutor never counts at full weight. Then ``1`` if ``discounted >= 0.25``
    else ``0`` (neutral 0.5 → discounted 0.25 → treated as a weak correct).
    """
    discounted = max(0.0, min(1.0, interaction_score)) * 0.5
    return 1 if discounted >= 0.25 else 0


def _whole_word_count(text: str, keyword: str) -> int:
    """Count whole-word / whole-phrase hits so short tokens like ``ac`` cannot match inside ``stomach``."""
    kw = keyword.lower().strip()
    if not kw:
        return 0
    pattern = r"(?<!\w)" + re.escape(kw) + r"(?!\w)"
    return len(re.findall(pattern, text))


def _score_text_for_topic(text: str, topic_id: str) -> int:
    """Keyword + alias scoring for one topic against normalized student text.

    Short curriculum tokens (``ac``, ``dc``, ``ph``) must match as whole words.
    Retrieval boost blurbs are not scored here — they are chapter descriptions,
    not student language.
    """
    low = text.lower()
    words = set(re.sub(r"[^\w\s]", " ", low).split())
    score = 0
    keywords = list(_TOPIC_KEYWORDS.get(topic_id, []))
    keywords.extend(_STUDENT_TOPIC_ALIASES.get(topic_id, []))

    for kw in keywords:
        kw_low = kw.lower().strip()
        if not kw_low:
            continue
        hits = _whole_word_count(low, kw_low)
        if hits:
            score += hits + 2
            continue
        # Fuzzy stem only for longer tokens. Use 7+ chars so
        # "heterotrophic" does not collide with "heterogeneous".
        if len(kw_low) < 7:
            continue
        kw_prefix = kw_low[:7]
        for w in words:
            if len(w) < 7:
                continue
            if w.startswith(kw_prefix) or kw_low.startswith(w[:7]):
                score += 1
                break
    return score


def _normalize_grade_level(grade: Optional[Any]) -> Optional[int]:
    if grade is None or grade == "":
        return None
    try:
        value = int(grade)
    except (TypeError, ValueError):
        return None
    if value < 6 or value > 9:
        return None
    return value


def _fallback_topic_for_grade(grade: Optional[int]) -> str:
    g = _normalize_grade_level(grade)
    if g is None:
        return FALLBACK_TOPIC_ID
    prefix = f"G{g}_"
    for topic_id in _TOPIC_KEYWORDS:
        if str(topic_id).startswith(prefix):
            return str(topic_id)
    return FALLBACK_TOPIC_ID


def _topic_ids_for_inference(grade: Optional[int] = None) -> list[str]:
    """Curriculum skills eligible for auto-routing (optionally grade-scoped)."""
    g = _normalize_grade_level(grade)
    if g is None:
        return list(_TOPIC_KEYWORDS.keys())
    prefix = f"G{g}_"
    scoped = [tid for tid in _TOPIC_KEYWORDS if str(tid).startswith(prefix)]
    return scoped or list(_TOPIC_KEYWORDS.keys())


_TOPIC_SWITCH_INTENT_RE = re.compile(
    r"(?:\?|^|\b)"
    r"(?:what|why|how|when|where|which|who|explain|describe|teach|tell|"
    r"can\s+you|could\s+you|i\s+want\s+to\s+(?:ask|know|learn)|"
    r"(?:change|switch|move)\s+(?:the\s+)?topic|new\s+topic|what\s+about)\b",
    flags=re.IGNORECASE,
)


def _rank_topics_for_text(
    text: str,
    *,
    grade: Optional[int] = None,
) -> list[tuple[str, int]]:
    """Return curriculum topics ranked by evidence in the current learner message."""
    normalized = re.sub(r"[^\w\s]", " ", str(text or "").strip().lower())
    ranked = [
        (topic_id, _score_text_for_topic(normalized, topic_id))
        for topic_id in _topic_ids_for_inference(grade)
    ]
    return sorted(ranked, key=lambda item: item[1], reverse=True)


def _resolve_topic_for_turn(
    user_id: str,
    student_answer: str,
    topic_id: Optional[str],
    conversation_history: Optional[list[dict[str, Any]]],
    *,
    grade: Optional[int] = None,
) -> tuple[str, Literal["explicit", "inferred", "continued", "switched"]]:
    """
    Resolve the lesson without allowing short Socratic answers to reroute the chat.

    A supplied topic is authoritative. With prior conversation history, the last
    resolved topic remains sticky unless the learner clearly asks a new,
    confidently classifiable science question. An empty history starts a fresh
    inference so user-level state does not permanently lock later conversations.
    When ``grade`` is set (6–9), inference only considers that grade's skills.
    """
    if topic_id:
        return normalize_topic_id(topic_id), "explicit"

    uid = str(user_id)
    prior_topic = _last_resolved_topic_by_user.get(uid)
    inferred_topic = infer_topic_id_from_question(
        student_answer,
        conversation_history=conversation_history,
        grade=grade,
    )
    if not prior_topic or not conversation_history:
        return inferred_topic, "inferred"

    ranked = _rank_topics_for_text(student_answer, grade=grade)
    best_topic, best_score = ranked[0] if ranked else (inferred_topic, 0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    has_switch_intent = bool(_TOPIC_SWITCH_INTENT_RE.search(student_answer))
    confident_new_topic = (
        best_topic != prior_topic
        and best_score >= 3
        and best_score - second_score >= 2
    )
    if has_switch_intent and confident_new_topic:
        return best_topic, "switched"
    return prior_topic, "continued"


def _prior_user_message(
    conversation_history: Optional[list[dict[str, Any]]],
) -> Optional[str]:
    if not conversation_history:
        return None
    for turn in reversed(conversation_history):
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role") or "").strip().lower() == "user":
            content = str(turn.get("content") or "").strip()
            if content:
                return content
    return None


def _scope_history_for_topic(
    user_id: str,
    resolved_topic: str,
    conversation_history: Optional[list[dict[str, Any]]],
) -> tuple[Optional[list[dict[str, Any]]], bool]:
    """
    When the learner switches lessons mid-chat, drop prior transcript so the LLM
    is not conditioned on a different topic. BKT remains per-topic regardless.
    """
    uid = str(user_id)
    prior_topic = _last_resolved_topic_by_user.get(uid)
    topic_changed = bool(prior_topic and prior_topic != resolved_topic)
    _last_resolved_topic_by_user[uid] = resolved_topic
    if topic_changed:
        return None, True
    return conversation_history, False


def _retrieval_source_summary(kb: dict[str, Any]) -> str:
    sources: set[str] = set()
    for ctx in kb.get("contexts") or []:
        if not isinstance(ctx, dict):
            continue
        meta = ctx.get("metadata") or {}
        if isinstance(meta, dict):
            name = str(meta.get("source_pdf") or "").strip()
            if name:
                sources.add(name)
    if sources:
        return ", ".join(sorted(sources))
    return "official syllabus PDFs (grade 6–9)"


def infer_topic_id_from_question(
    student_answer: str,
    *,
    conversation_history: Optional[list[dict[str, Any]]] = None,
    fallback_topic_id: Optional[str] = None,
    grade: Optional[int] = None,
) -> str:
    """
    Infer topic_id from natural language using the expanded ``_TOPIC_KEYWORDS`` catalog.

    Scores the latest student message; for short follow-ups (e.g. \"why?\", \"yes\"),
    also scores against the most recent prior user turn.
    When ``grade`` is 6–9, only skills for that grade are considered.
    """
    fallback = fallback_topic_id or _fallback_topic_for_grade(grade)
    text = student_answer.strip().lower()
    if not text:
        return fallback

    text = re.sub(r"[^\w\s]", " ", text)
    scoring_segments = [text]
    prior = _prior_user_message(conversation_history)
    if prior and len(text.split()) <= 4:
        scoring_segments.append(re.sub(r"[^\w\s]", " ", prior.strip().lower()))

    best_topic = fallback
    best_score = 0
    for topic_id in _topic_ids_for_inference(grade):
        score = sum(_score_text_for_topic(segment, topic_id) for segment in scoring_segments)
        if score > best_score:
            best_score = score
            best_topic = topic_id
    return best_topic


def generate_socratic_hint(
    user_id: str,
    topic_id: str,
    student_answer: str,
    *,
    conversation_history: Optional[list[dict[str, Any]]] = None,
    bkt: Optional[ScienceBKT] = None,
    context_k: int = 4,
    persona_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Combine BKT mastery, local RAG context, and an LLM to produce a Socratic hint.

    Dialogue mastery updates follow ``TUTOR_BKT_POLICY`` (default ``quiz_only``).
    Missing or invalid ``interaction_score`` → no BKT update that turn.

    Parameters
    ----------
    user_id, topic_id :
        Passed through to the learner model and retriever (topic_id must match log skill ids, e.g. G6_... / G7_...).
    student_answer :
        The learner's latest free-text response.
    conversation_history :
        Prior transcript as ``[{"role":"user"|"assistant","content":str}]`` excluding this latest line.
    bkt :
        Optional shared ScienceBKT instance; otherwise a module-level default engine is used.
    context_k :
        Number of syllabus chunks to retrieve.
    persona_id :
        Optional tutor persona (``practical_encourager``, ``analytical_coach``,
        ``curious_explorer``). High frustration still forces Practical Encourager.
        If omitted and frustration is not high, server picks ``TUTOR_DEFAULT_PERSONA``
        or rotates randomly each turn.
    """
    # Ensure .env variables (including HF_TOKEN / GROQ_API_KEY) are available
    # before retrieval and model calls.
    _load_env()
    if topic_id:
        ensure_gaming_frustration_cue(user_id, normalize_topic_id(topic_id))

    if _is_greeting_intent(student_answer):
        return _greeting_opener_response(
            user_id=user_id,
            persona_id=persona_id,
            student_answer=student_answer,
            topic_id=topic_id,
            bkt=bkt,
        )

    if _is_acknowledgment_intent(student_answer):
        return _acknowledgment_closure_response(
            user_id=user_id,
            topic_id=topic_id,
            persona_id=persona_id,
            student_answer=student_answer,
            bkt=bkt,
            topic_id_inferred=False,
            topic_changed=False,
        )

    topic_id = normalize_topic_id(topic_id)
    engine = bkt or _get_default_bkt()
    mastery_before = float(engine.get_current_mastery_probability(user_id, topic_id))
    try:
        kb = retrieve_context(topic_id, k=context_k)
    except Exception:
        kb = {
            "topic_id": topic_id,
            "query_used": None,
            "chunks_returned": 0,
            "contexts": [],
            "facts_text": "",
            "skipped": True,
            "skip_reason": "rag_unavailable",
        }
    facts = (kb.get("facts_text") or "").strip()
    source_summary = _retrieval_source_summary(kb)
    mode = _hint_mode(mastery_before)
    frustration_resolution = resolve_frustration_for_turn(user_id, topic_id, student_answer)
    resolved_persona = _resolve_persona_id(
        persona_id,
        user_id,
        frustration_level=frustration_resolution.level,
    )
    persona_label = _PERSONA_LABELS[resolved_persona]
    tone_guidance = _tone_guidance_from_frustration(frustration_resolution)
    frustration_audit = build_frustration_audit_fields(frustration_resolution, resolved_persona)

    help_intent = _is_help_intent(student_answer)
    last_follow_up = _last_tutor_follow_up(conversation_history)
    attempt = _is_attempt_intent(student_answer, last_follow_up)
    answer_seeking = (not attempt) and _is_answer_seeking_intent(student_answer)
    hist_block = _format_conversation_history(conversation_history)
    thread_prefix = (
        f"Recent conversation (older messages first; Student vs Tutor labels are exact):\n{hist_block}\n\n"
        if hist_block
        else ""
    )
    help_prefix = ""
    if help_intent:
        prior = last_follow_up or "(no previous tutor question — give a tiny clue on the topic)"
        help_prefix = (
            "TURN TYPE: help_request. The student did NOT answer. They are stuck on your "
            f"previous follow-up:\n\"{prior}\"\n"
            "Scaffold THAT question with one smaller clue. Do not invent what they thought. "
            "Do not give the full definition or formula. interaction_score should be 0.15–0.30.\n\n"
        )
    elif answer_seeking:
        help_prefix = (
            "TURN TYPE: answer_seeking. They asked a science question "
            "(why / what / how / need / used for / …). "
            "Do NOT answer it "
            "(no \"fish use gills to take oxygen from water\", "
            "no \"acids turn blue litmus red\", no \"sodium is in salt / nerves / fluids\"). "
            "Clues + one prediction question only. interaction_score 0.20–0.40.\n\n"
        )
    elif attempt:
        help_prefix = (
            "TURN TYPE: attempt. They replied to your previous follow-up:\n"
            f"\"{last_follow_up}\"\n"
            "Validate that reply FIRST. Sentence 1 must be Yes that's right / Not quite / "
            "Partly right. Only then give one next Socratic step and one new question. "
            "If wrong, do not dump the correct fact. Score clearly: correct usually ≥0.78; "
            "wrong/vague usually ≤0.35.\n\n"
        )
    user_block = (
        f"topic_id: {topic_id}\n"
        f"estimated_mastery_probability: {mastery_before:.4f}\n"
        f"hint_mode: {mode}\n"
        f"persona_id: {resolved_persona}\n"
        f"persona_label: {persona_label}\n\n"
        f"frustration_signal_level: {frustration_resolution.level or 'none'}\n"
        f"frustration_effective_score: {frustration_resolution.effective_score:.4f}\n"
        f"frustration_source_tag: {frustration_resolution.source_tag}\n\n"
        f"{thread_prefix}"
        f"{help_prefix}"
        f"PRIVATE tutor curriculum notes (do NOT mention these notes, excerpts, or any "
        f"textbook/source to the student; {source_summary}; may be partial; "
        f"{'use them to JUDGE this attempt and to know which fact to WITHHOLD' if attempt else 'use them only to know which fact to WITHHOLD'} "
        f"— never copy the answer into hint_text):\n"
        f"{facts if facts else '[no curriculum notes retrieved]'}\n\n"
        f"Student's **latest** message (verbatim"
        f"{'; HELP request, not a science answer' if help_intent else ''}"
        f"{'; they asked a question — do not answer it' if answer_seeking else ''}"
        f"{'; they answered your last follow-up — validate it first' if attempt else ''}):\n"
        f"{student_answer.strip() or '[empty]'}\n\n"
        f"{_reply_constraints(resolved_persona, answer_seeking=answer_seeking, attempt=attempt)}"
    )

    try:
        client, model = _make_llm_client()

        def _invoke_once() -> tuple[str, Optional[float], Optional[str]]:
            response = client.invoke(
                [
                    SystemMessage(
                        content=_build_system_prompt(
                            mode,
                            resolved_persona,
                            tone_guidance,
                            help_intent=help_intent,
                            answer_seeking=answer_seeking,
                            attempt=attempt,
                        )
                    ),
                    HumanMessage(content=user_block),
                ],
                max_tokens=_tutor_llm_max_tokens(),
            )
            raw_content = _llm_response_text(response.content)
            h_text, p_score, p_err = _parse_llm_json_payload(raw_content)
            return h_text, p_score, p_err

        hint_text, parsed_score, parse_err = _invoke_once()
        # One-time retry for malformed/empty payloads to reduce user-facing fallback prompts.
        if parse_err and (
            parse_err.startswith("json_decode_error")
            or parse_err == "empty_model_response"
            or not (hint_text or "").strip()
        ):
            retry_hint_text, retry_parsed_score, retry_parse_err = _invoke_once()
            # Use retry output when it is cleaner or valid.
            if (
                not retry_parse_err
                or (retry_hint_text or "").strip()
                or retry_parsed_score is not None
            ):
                hint_text, parsed_score, parse_err = (
                    retry_hint_text,
                    retry_parsed_score,
                    retry_parse_err,
                )

    except Exception as exc:
        return {
            "success": False,
            "user_id": str(user_id),
            "topic_id": str(topic_id),
            "mastery_probability": mastery_before,
            "mastery_probability_before": mastery_before,
            "updated_mastery_probability": mastery_before,
            "hint_mode": mode,
            "persona_id": resolved_persona,
            "persona_label": persona_label,
            "hint_text": "",
            "interaction_score": None,
            "interaction_score_effective": None,
            "bkt_updated": False,
            "risk_flag": False,
            "bkt_update_note": None,
            "retrieval": {
                "chunks_returned": kb.get("chunks_returned"),
                "query_used": kb.get("query_used"),
            },
            "frustration_level_used": frustration_resolution.level,
            "frustration_score_used": frustration_resolution.effective_score,
            **frustration_audit,
            "tutor_bkt_policy": _tutor_bkt_policy(),
            "llm_model": None,
            "error": str(exc),
        }

    if parse_err and (
        parse_err.startswith("json_decode_error")
        or parse_err == "empty_model_response"
        or not (hint_text or "").strip()
    ):
        hint_text = (
            "I had trouble reading the tutor response just now. "
            "Please try sending your message again."
        )
    else:
        hint_text = enforce_single_follow_up_question(hint_text)
    if help_intent and parsed_score is not None:
        parsed_score = min(float(parsed_score), 0.30)
    elif answer_seeking and parsed_score is not None:
        parsed_score = min(float(parsed_score), 0.40)

    mastery_after = mastery_before
    bkt_updated = False
    bkt_note: Optional[str] = parse_err
    risk_flag = False
    bkt_snapshot: Optional[dict[str, Any]] = None
    bkt_label: Optional[int] = None
    score_effective: Optional[float] = None

    if parsed_score is not None:
        score_effective = max(0.0, min(1.0, float(parsed_score)))
        bkt_label, skip_reason = _dialogue_score_to_bkt_label(score_effective)
        if bkt_label is None:
            bkt_note = skip_reason or "dialogue_bkt_skipped"
            mastery_after = mastery_before
        else:
            try:
                bkt_snapshot = engine.predict_update(user_id, topic_id, bkt_label, None)
                mastery_after = float(engine.get_current_mastery_probability(user_id, topic_id))
                bkt_updated = True
                risk_flag = bool(bkt_snapshot.get("at_risk"))
                bkt_note = None
            except ValueError as exc:
                bkt_note = str(exc)
                mastery_after = mastery_before
    else:
        bkt_note = parse_err or "no_interaction_score_bkt_skipped"

    consume_frustration_after_hint(user_id, topic_id, score_effective)

    coach_steps, coach_question = ([], None)
    if resolved_persona == "analytical_coach":
        coach_steps, coach_question = extract_analytical_steps(hint_text)

    return {
        "success": True,
        "user_id": str(user_id),
        "topic_id": str(topic_id),
        "mastery_probability": mastery_after,
        "mastery_probability_before": mastery_before,
        "updated_mastery_probability": mastery_after,
        "hint_mode": mode,
        "persona_id": resolved_persona,
        "persona_label": persona_label,
        "hint_text": hint_text,
        "hint_steps": coach_steps,
        "closing_question": coach_question,
        "interaction_score": parsed_score,
        "interaction_score_effective": score_effective,
        "bkt_updated": bkt_updated,
        "bkt_observation_label": bkt_label,
        "tutor_bkt_policy": _tutor_bkt_policy(),
        "bkt_update_note": bkt_note,
        "risk_flag": risk_flag,
        "retrieval": {
            "chunks_returned": kb.get("chunks_returned"),
            "query_used": kb.get("query_used"),
        },
        "frustration_level_used": frustration_resolution.level,
        "frustration_score_used": frustration_resolution.effective_score,
        **frustration_audit,
        "llm_model": model,
    }


def generate_socratic_hint_auto_topic(
    user_id: str,
    student_answer: str,
    *,
    topic_id: Optional[str] = None,
    conversation_history: Optional[list[dict[str, Any]]] = None,
    bkt: Optional[ScienceBKT] = None,
    context_k: int = 4,
    persona_id: Optional[str] = None,
    grade: Optional[int] = None,
) -> dict[str, Any]:
    """
    Generate a hint when only free-text question/answer is provided.

    If topic_id is supplied, it is authoritative. Otherwise infer the first
    topic, retain it for conversational follow-ups, and switch only when the
    learner clearly asks a confidently classifiable question about another topic.
    When the resolved topic changes, prior chat history is not sent to the LLM.

    ``grade`` (6–9) scopes auto-routing to that grade's skills so a Grade 6
    question cannot lock onto a Grade 9 skill id.

    Acknowledgment / gratitude and standalone greetings short-circuit before
    topic inference and RAG.
    """
    grade_level = _normalize_grade_level(grade)
    sticky_for_cue = (
        topic_id
        or _last_resolved_topic_by_user.get(str(user_id))
        or _fallback_topic_for_grade(grade_level)
    )
    ensure_gaming_frustration_cue(user_id, normalize_topic_id(sticky_for_cue))

    if _is_greeting_intent(student_answer):
        response = _greeting_opener_response(
            user_id=user_id,
            persona_id=persona_id,
            student_answer=student_answer,
            topic_id=topic_id,
            bkt=bkt,
        )
        response["topic_routing"] = "none"
        return response

    if _is_acknowledgment_intent(student_answer):
        sticky_topic = (
            topic_id
            or _last_resolved_topic_by_user.get(str(user_id))
            or _fallback_topic_for_grade(grade_level)
        )
        response = _acknowledgment_closure_response(
            user_id=user_id,
            topic_id=normalize_topic_id(sticky_topic),
            persona_id=persona_id,
            student_answer=student_answer,
            bkt=bkt,
            topic_id_inferred=topic_id is None,
            topic_changed=False,
        )
        response["topic_routing"] = "explicit" if topic_id else "continued"
        return response

    resolved_topic, topic_routing = _resolve_topic_for_turn(
        user_id,
        student_answer,
        topic_id,
        conversation_history,
        grade=grade_level,
    )
    scoped_history, topic_changed = _scope_history_for_topic(
        user_id,
        resolved_topic,
        conversation_history,
    )
    result = generate_socratic_hint(
        user_id=user_id,
        topic_id=resolved_topic,
        student_answer=student_answer,
        conversation_history=scoped_history,
        bkt=bkt,
        context_k=context_k,
        persona_id=persona_id,
    )
    result["topic_id_inferred"] = topic_id is None
    result["topic_id_resolved"] = resolved_topic
    result["topic_routing"] = topic_routing
    result["topic_changed"] = topic_changed
    result["history_turns_sent"] = len(scoped_history or [])
    if grade_level is not None:
        result["grade_scoped"] = grade_level
    return result


__all__ = [
    "generate_socratic_hint",
    "generate_socratic_hint_auto_topic",
    "get_shared_bkt_engine",
    "infer_topic_id_from_question",
    "upsert_frustration_signal",
    "ensure_gaming_frustration_cue",
    "score_frustration_from_chat",
    "resolve_frustration_for_turn",
    "consume_frustration_after_hint",
    "build_frustration_audit_fields",
    "FrustrationSignal",
    "FrustrationResolution",
]
