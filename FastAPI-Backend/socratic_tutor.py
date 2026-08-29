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
            "- Lead with a vivid everyday metaphor (plumbing, cooking, sport, weather) that matches "
            "the science you know from your private curriculum notes.\n"
            "- Sound warmly supportive; normalize that the idea is tricky before asking one small question.\n"
            "- Give enough concrete logic that the student senses the distinction before you ask.\n"
            "- Follow-up must be about the real-world science situation—not about a book or passage."
        ),
        "balanced": (
            "PERSONA × MODE: Practical Encourager · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- Briefly mirror something the student said, then link it to a real-world comparison.\n"
            "- Offer one crisp contrast in plain language; avoid re-teaching the whole topic.\n"
            "- Close with one discrimination question (same vs different, or which situation fits)."
        ),
        "nudge": (
            "PERSONA × MODE: Practical Encourager · NUDGE (P(L) > 0.8).\n"
            "- At most one short recap sentence; no long analogy chains.\n"
            "- Pose an everyday mini-scenario: \"If you tried this at home / on a walk, what would you notice?\"\n"
            "- Push transfer to a new situation without giving the final label or answer."
        ),
    },
    "analytical_coach": {
        "scaffold": (
            "PERSONA × MODE: Analytical Coach · SCAFFOLD (P(L) < 0.5).\n"
            "- Break the idea into 2–3 numbered micro-steps (cause → mechanism → outcome).\n"
            "- Speak with quiet certainty about the mechanism; never invent numbers or claim "
            "\"the text says\".\n"
            "- End with one step-check question: \"What happens first in that chain?\""
        ),
        "balanced": (
            "PERSONA × MODE: Analytical Coach · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- Compare two terms or mechanisms side-by-side using a tight if/then structure.\n"
            "- Highlight one decisive physical variable (path, temperature, medium, etc.).\n"
            "- Ask which real-world condition would flip the outcome."
        ),
        "nudge": (
            "PERSONA × MODE: Analytical Coach · NUDGE (P(L) > 0.8).\n"
            "- Skip basics; invite them to predict how changing ONE variable alters the mechanism.\n"
            "- Frame as a logical consequence in the physical world, not a lecture.\n"
            "- One precise hypothetical: \"If we changed X, what would the next step in the process be?\""
        ),
    },
    "curious_explorer": {
        "scaffold": (
            "PERSONA × MODE: Curious Explorer · SCAFFOLD (P(L) < 0.5).\n"
            "- Treat the concept like a puzzle: share one scientific clue, withhold the label.\n"
            "- Invite a hypothesis in plain words (\"What might be going on here?\").\n"
            "- Keep wonder in the tone—never sound like a verdict or a reading quiz."
        ),
        "balanced": (
            "PERSONA × MODE: Curious Explorer · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- Acknowledge a partial insight, then open a \"what if\" that splits two close ideas.\n"
            "- Use science-as-mystery framing grounded in one curriculum-supported idea.\n"
            "- One curiosity-driving question about the physical world—not a multi-part quiz."
        ),
        "nudge": (
            "PERSONA × MODE: Curious Explorer · NUDGE (P(L) > 0.8).\n"
            "- Pose a counterfactual that stretches the idea to an unfamiliar real-world case.\n"
            "- Ask what they would expect to observe or measure—not what a document would say.\n"
            "- Final line must be openly hypothetical (\"Suppose … then what changes?\")."
        ),
    },
}

_SOCRATIC_GUARDRAILS = """
--- NON-NEGOTIABLE SOCRATIC GUARDRAILS (all personas, all modes) ---
1. PRIVATE GROUNDING: The curriculum snippets in the user message are YOUR private tutor notes
   (from ``science_syllabus_g6_g9``). Internalize them and speak as an omniscient science tutor
   who already knows this material. Never invent facts outside those notes. If the notes are
   empty or silent on a point, say you are unsure about that detail—without mentioning a book,
   excerpt, PDF, or retrieval system.
2. BAN META-COMMENTARY IN hint_text: Never use phrases such as \"the excerpt\", \"the text\",
   \"the textbook\", \"the passage\", \"the reading\", \"according to the text\", \"the text
   suggests/states/says\", \"the curriculum says\", or reference filenames, page numbers,
   figures, or \"snippet\" IDs. Do not ask the student to quote, find, or recall wording from
   any document they cannot see.
3. EMBODIED KNOWLEDGE: Synthesize the private notes into natural conversational science
   guidance. Talk about materials, forces, organisms, and everyday situations—not about sources.
4. FOLLOW-UP = SCIENCE, NOT READING COMPREHENSION: Your single closing question must challenge
   conceptual understanding of the physical world (what happens, why, which condition changes
   the outcome). BAD: \"What might the text suggest happens when the wet stick touches the
   wire?\" GOOD: \"Since water behaves differently than dry wood, what do you think happens to
   that electrical current when it meets the damp stick in your hand?\" If the student
   themselves mentions \"textbook\", still answer about the science—do not echo that framing.
5. NO DIRECT ANSWERS: Never state the full final answer, complete definition, numeric result,
   worked solution, or \"the correct term is ___\" in hint_text. Scaffolding and hints only.
6. NO STRUCTURAL DUMPS: Do not dump labeled sections, full lists, or theorem-like pronouncements.
   Guide the student to articulate the idea themselves.
7. ONE QUESTION: hint_text ends with exactly ONE inviting science question (not a stack).
8. BREVITY: hint_text ≤ 120 words; short paragraphs; no markdown fences in hint_text.
9. VARIETY: Do NOT use canned openers (\"Great job!\", \"Good start!\", \"That's a great start!\",
   \"Excellent question!\"). Open naturally and differently each turn.
10. JSON ONLY: Return a single JSON object with hint_text and interaction_score—no extra keys.
""".strip()

# Few-shot demonstrations: native tutor voice (no meta \"text/excerpt\" references).
_FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "I don't get conductors vs insulators.",
        "hint": "Think of a hallway where some doors let people through easily and others stay shut—that's how materials behave with electric flow. Metals act more like open doors, while rubber acts more like a locked one. Which everyday object in your kitchen might act like an open door for electricity?",
    },
    {
        "persona": "practical_encourager",
        "mode": "balanced",
        "student": "Renewable and non-renewable—are they the same thing?",
        "hint": "You picked up that both are energy sources—the key split is whether the supply can be replenished on a human timescale, like sunshine returning each day versus coal taking millions of years to form. Which of those two timescales sounds closer to \"runs out for good\"?",
    },
    {
        "persona": "practical_encourager",
        "mode": "nudge",
        "student": "Solid liquid gas—I think I've got it.",
        "hint": "You've linked the three states. Imagine you leave a puddle on a hot pavement: as the water disappears into the air, what change of state is happening, and what would you expect to feel near that puddle while it lasts?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "student": "What is photosynthesis?",
        "hint": "Let's sequence it: (1) light hits the leaf, (2) chlorophyll captures that energy, (3) carbon dioxide and water are combined to store energy in sugars. Which of those inputs must come from the air rather than the soil?",
    },
    {
        "persona": "analytical_coach",
        "mode": "balanced",
        "student": "Series and parallel circuits confuse me.",
        "hint": "Focus on path count: one loop versus branches. In series, current has a single route; in parallel, it can split. If one lamp burned out in a series string, what happens to the remaining path for current?",
    },
    {
        "persona": "analytical_coach",
        "mode": "nudge",
        "student": "Density is mass over volume, right?",
        "hint": "Your ratio is pointed the right way. If we kept mass fixed but doubled volume only, would density go up or down—and what would you notice if you compared those two samples side by side?",
    },
    {
        "persona": "curious_explorer",
        "mode": "scaffold",
        "student": "Why do living things need nutrition?",
        "hint": "Here's one clue: living things take in materials they cannot stay alive without. Nutrition is not just \"eating for fun\"—it fuels growth and repair. What do you think happens to an organism that stops taking in those materials?",
    },
    {
        "persona": "curious_explorer",
        "mode": "balanced",
        "student": "Acids and bases feel like opposites.",
        "hint": "You're sensing a real pairing. Acids and bases show themselves through how they react with indicators—not just by being random opposites. If an indicator turned one color in lemon juice, what would you expect when a base is added slowly?",
    },
    {
        "persona": "curious_explorer",
        "mode": "nudge",
        "student": "Refraction is when light bends.",
        "hint": "Bending is the visible part—and it connects to speed changes when light crosses between media. Suppose light travels from air into much denser water: would the ray hug the normal more or drift farther from it?",
    },
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "I can't tell vertebrates from invertebrates.",
        "hint": "Picture a backbone like a central tent pole inside some animals but missing in others—that internal support is how we split the groups. Worms and insects fall on one side; fish and birds on the other. Where would a spider land, based on that pole idea?",
    },
    {
        "persona": "analytical_coach",
        "mode": "balanced",
        "student": "Monocots vs dicots?",
        "hint": "Compare seed-leaf count and vein patterns. Monocots show parallel veins; dicots show net-like veins. If you only had a leaf drawing, which vein pattern would you measure first?",
    },
    {
        "persona": "curious_explorer",
        "mode": "nudge",
        "student": "Sound needs a medium—I remember that.",
        "hint": "Sound needs something to travel through, so vacuum gaps block it. What if an astronaut tapped helmet to helmet with no air between—would the vibration still have a material path to travel?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "student": "Earth's layers are confusing.",
        "hint": "Work outside-in: crust, then mantle, then core—each layer has its own thickness or state. Which layer sits directly under the crust you stand on?",
    },
    {
        "persona": "practical_encourager",
        "mode": "nudge",
        "student": "Evaporation and boiling—same thing?",
        "hint": "They're related but happen at different scales. Boiling hits the whole liquid at a set temperature; evaporation can happen quietly at the surface. On a windy day at the lake, which process would you notice first without a thermometer?",
    },
    {
        "persona": "curious_explorer",
        "mode": "balanced",
        "student": "What carries oxygen in blood?",
        "hint": "A specific component inside red blood cells binds oxygen—not the plasma alone. If that component were missing, which job in circulating blood would fail first?",
    },
    {
        "persona": "practical_encourager",
        "mode": "nudge",
        "student": "If I used a wet wooden stick to poke a live wire, what would the textbook say could happen?",
        "hint": "Dry wood usually resists electric flow, but water can change that picture—wet wood can start to behave more like a path for current. Since water behaves differently than dry wood, what do you think happens to that electrical current when it meets the damp stick in your hand?",
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
                "topic_id": USER_LEVEL_FRUSTRATION_TOPIC,
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
            "Frustration signal is MEDIUM. Be supportive and clear; keep corrections gentle, "
            "avoid dense jargon, and prefer one focused question over a multi-part drill."
        )
    return (
        "Frustration signal is LOW. Keep positive tone and normal Socratic pacing."
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
        label = "Student" if role == "user" else "Tutor"
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
        "Hello. I can walk you through any Grade 6–9 science concept step by step. "
        "Which topic should we start with?"
    ),
    "curious_explorer": (
        "Hey! Ready to investigate a science idea? "
        "What topic can I help you with?"
    ),
}


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
    max_examples: int = 12,
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
) -> str:
    persona_label = _PERSONA_LABELS[persona]
    state_config = _PERSONA_STATE_MATRIX[persona][mode]
    few_shots = _format_few_shot_examples(persona, mode)

    return (
        f"You are **{persona_label}**, a Grade 6–9 science tutor using a multi-persona "
        f"Socratic scaffolding engine.\n"
        f"Active state: persona_id={persona}, hint_mode={mode}.\n"
        f"You speak as a natural, omniscient tutor. Private curriculum notes appear in the user "
        f"message for YOUR eyes only (collection ``science_syllabus_g6_g9``). Internalize those "
        f"facts and coach in your own voice. Never reveal the notes as \"text\", \"excerpts\", or "
        f"\"the textbook\". If the student's ideas conflict with that knowledge, gently redirect "
        f"using plain science language—not source citations.\n\n"
        f"{_SOCRATIC_GUARDRAILS}\n\n"
        f"--- Active persona × mastery configuration (9-state matrix cell) ---\n"
        f"{state_config}\n\n"
        f"--- Conversational continuity ---\n"
        f"- THREAD: If a recent transcript is included, the student's latest message often "
        f"answers your previous question. Acknowledge that answer before scaffolding further.\n"
        f"- MEMORY: Paraphrase a concrete phrase from their latest message so your reply "
        f"clearly responds to their words.\n"
        f"- FIGURES / LABELS: Do not mention figures, diagrams, exercises, tables, or page "
        f"references. Describe the science idea in plain language instead.\n"
        f"- SENTIMENT ADAPTATION: {tone_guidance}\n"
        f"  When frustration is high, soften delivery while still correcting misconceptions "
        f"and staying faithful to your private curriculum notes.\n\n"
        f"--- Correction-first protocol ---\n"
        f"If their science content is wrong relative to your private notes:\n"
        f"  1) Brief validation of effort or intent (vary phrasing—no canned praise headers).\n"
        f"  2) Gentle correction via analogy or contrast about the physical world.\n"
        f"  3) Exactly ONE follow-up question about conceptual understanding (never reading "
        f"comprehension of an invisible document).\n"
        f"If substantially correct, validate briefly and bridge before your one question.\n\n"
        f"--- Few-shot reference conversations (study style, not facts) ---\n"
        f"These show natural persona voice across BKT modes—no meta \"text/excerpt\" talk. "
        f"Do NOT copy their science content unless your private curriculum notes support it.\n\n"
        f"{few_shots}\n\n"
        f"--- interaction_score (JSON field only; never shown in hint_text) ---\n"
        f"Set \"interaction_score\" from 0.0 to 1.0 for how well their **latest** answer matches "
        f"correct science per your private curriculum notes. Be calibrated: wrong/vague usually "
        f"≤0.35; major misconception ≤0.25; only clearly correct ≥0.78.\n"
        f"  • 0.0–0.35: wrong, vague, or major misconception\n"
        f"  • 0.36–0.77: partial / uncertain (not mastered)\n"
        f"  • 0.78–1.0: clearly correct and curriculum-aligned\n\n"
        f"--- OUTPUT FORMAT (mandatory) ---\n"
        f"Return ONLY a single JSON object with exactly two keys: \"hint_text\" (string, "
        f"≤120 words) and \"interaction_score\" (number). Example: "
        f'{{"hint_text":"...","interaction_score":0.55}}\n'
        f"If interaction_score is missing or not a number, the server skips dialogue-derived "
        f"BKT logic for this turn—always include a valid number.\n"
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
    kb = retrieve_context(topic_id, k=context_k)
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

    hist_block = _format_conversation_history(conversation_history)
    thread_prefix = (
        f"Recent conversation (older messages first; use this for continuity):\n{hist_block}\n\n"
        if hist_block
        else ""
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
        f"PRIVATE tutor curriculum notes (do NOT mention these notes, excerpts, or any "
        f"textbook/source to the student; {source_summary}; may be partial):\n"
        f"{facts if facts else '[no curriculum notes retrieved]'}\n\n"
        f"Student's **latest** message (verbatim; reply to Tutor above if answering a question):\n"
        f"{student_answer.strip() or '[empty]'}\n"
    )

    try:
        client, model = _make_llm_client()

        def _invoke_once() -> tuple[str, Optional[float], Optional[str]]:
            response = client.invoke(
                [
                    SystemMessage(
                        content=_build_system_prompt(mode, resolved_persona, tone_guidance)
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
