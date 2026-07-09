"""
Socratic tutoring hints grounded in BKT mastery and the local syllabus RAG index.

**Mastery architecture (single state per learner per skill):** There is one
process-wide ``ScienceBKT`` and one ``student_state[(user_id, skill)]`` trajectory.
- **Assessment / quiz** (``POST /api/v1/assessment-submit`` in ``main.py``): pass
  verified ``is_correct`` into ``predict_update`` — ground-truth labels.
- **Dialogue** (this module): optional noisy BKT updates when scores are decisive
  (see ``TUTOR_BKT_POLICY``: ``strict`` / ``quiz_only`` / ``legacy``). Ambiguous scores
  skip updates under ``strict``. Missing/invalid scores → **no** BKT update that turn.

Uses Groq via langchain_groq (env-based). The tutor follows a state-aware Socratic
framework (correction-first when needed, mastery-tuned scaffolding).

Install:
    pip install langchain-groq python-dotenv

Environment:
  GROQ_API_KEY (loaded from .env)
  GROQ_MODEL_NAME: Groq model id (default ``openai/gpt-oss-120b``).
  TUTOR_LLM_MAX_TOKENS: optional int (default ``512``).
  TUTOR_BKT_POLICY: how dialogue updates BKT — ``strict`` (default): only clear
    correct/incorrect scores update mastery; ambiguous mid scores skip updates.
    ``quiz_only``: never update BKT from chat; use ``/api/v1/assessment-submit`` only.
    ``legacy``: old rule (score×0.5 then ≥0.25 ⇒ correct — very optimistic).
  TUTOR_LLM_TEMPERATURE: optional float (default ``0.35`` for steadier scoring).
  TUTOR_DEFAULT_PERSONA: optional persona_id if client omits one (else random per turn).
"""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from bkt_engine import ScienceBKT
from knowledge_base import _TOPIC_KEYWORDS, _TOPIC_QUERY_BOOST, retrieve_context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = PROJECT_ROOT / ".env"

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
            "- Lead with a vivid everyday metaphor (plumbing, cooking, sport, weather) tied to the excerpts.\n"
            "- Sound warmly supportive; normalize that the idea is tricky before asking one small question.\n"
            "- Give enough concrete logic that the student senses the distinction before you ask."
        ),
        "balanced": (
            "PERSONA × MODE: Practical Encourager · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- Briefly mirror something the student said, then link it to a real-world comparison from the excerpts.\n"
            "- Offer one crisp contrast in plain language; avoid re-teaching the whole topic.\n"
            "- Close with one discrimination question (same vs different, or which situation fits)."
        ),
        "nudge": (
            "PERSONA × MODE: Practical Encourager · NUDGE (P(L) > 0.8).\n"
            "- At most one short recap sentence; no long analogy chains.\n"
            "- Pose a everyday mini-scenario: \"If you tried this at home / on a walk, what would you notice?\"\n"
            "- Push transfer to a new situation without giving the final label or answer."
        ),
    },
    "analytical_coach": {
        "scaffold": (
            "PERSONA × MODE: Analytical Coach · SCAFFOLD (P(L) < 0.5).\n"
            "- Break the idea into 2–3 numbered micro-steps (cause → mechanism → outcome).\n"
            "- Use cautious data language (\"the excerpt suggests\", \"one pattern is\")—never invent numbers.\n"
            "- End with one step-check question: \"What happens first in that chain?\""
        ),
        "balanced": (
            "PERSONA × MODE: Analytical Coach · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- Compare two terms or mechanisms side-by-side using a tight if/then structure.\n"
            "- Highlight one variable the excerpts treat as decisive.\n"
            "- Ask which condition in the text would flip the outcome."
        ),
        "nudge": (
            "PERSONA × MODE: Analytical Coach · NUDGE (P(L) > 0.8).\n"
            "- Skip basics; invite them to predict how changing ONE variable alters the mechanism.\n"
            "- Frame as a logical consequence, not a lecture.\n"
            "- One precise hypothetical: \"If we changed X, what would the next step in the process be?\""
        ),
    },
    "curious_explorer": {
        "scaffold": (
            "PERSONA × MODE: Curious Explorer · SCAFFOLD (P(L) < 0.5).\n"
            "- Treat the concept like a puzzle: share one clue from the excerpts, withhold the label.\n"
            "- Invite a hypothesis in plain words (\"What might be going on here?\").\n"
            "- Keep wonder in the tone—never sound like a verdict."
        ),
        "balanced": (
            "PERSONA × MODE: Curious Explorer · BALANCED (0.5 ≤ P(L) ≤ 0.8).\n"
            "- Acknowledge a partial insight, then open a \"what if\" that splits two close ideas.\n"
            "- Use science-as-mystery framing; one thread from the textbook only.\n"
            "- One curiosity-driving question—not a multi-part quiz."
        ),
        "nudge": (
            "PERSONA × MODE: Curious Explorer · NUDGE (P(L) > 0.8).\n"
            "- Pose a counterfactual that stretches the idea to an unfamiliar case.\n"
            "- Ask what evidence from the excerpts would support or challenge their prediction.\n"
            "- Final line must be openly hypothetical (\"Suppose … then what changes?\")."
        ),
    },
}

_SOCRATIC_GUARDRAILS = """
--- NON-NEGOTIABLE SOCRATIC GUARDRAILS (all personas, all modes) ---
1. GROUNDING: Science claims must come ONLY from the retrieved textbook excerpts in the user
   message (``science_syllabus_g6_g9`` / scaled Grade 6–9 syllabus). If excerpts are silent, say
   you need more textbook context—do not invent facts.
2. NO DIRECT ANSWERS: Never state the full final answer, complete definition, numeric result,
   worked solution, or \"the correct term is ___\" in hint_text. Scaffolding and hints only.
3. NO STRUCTURAL REVEALS: Do not dump labeled textbook sections, full lists, or theorem-like
   pronouncements. Guide the student to articulate the idea themselves.
4. ONE QUESTION: hint_text ends with exactly ONE inviting question (not a stack).
5. BREVITY: hint_text ≤ 120 words; short paragraphs; no markdown fences in hint_text.
6. VARIETY: Do NOT use canned openers (\"Great job!\", \"Good start!\", \"That's a great start!\",
   \"Excellent question!\"). Open naturally and differently each turn.
7. JSON ONLY: Return a single JSON object with hint_text and interaction_score—no extra keys.
""".strip()

# Few-shot demonstrations: persona × mode variety without mechanical praise headers.
_FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "I don't get conductors vs insulators.",
        "hint": "Think of a hallway where some doors let people through easily and others stay shut—that's the spirit of what the excerpt describes about materials and electric flow. Metals tend to behave like open doors in the text's examples, while rubber acts more like a locked one. Which everyday object in your kitchen might act like an open door for electricity?",
    },
    {
        "persona": "practical_encourager",
        "mode": "balanced",
        "student": "Renewable and non-renewable—are they the same thing?",
        "hint": "You picked up that both are energy sources—the passage still separates them by whether the supply can be replenished on a human timescale, like sunshine returning each day versus coal taking millions of years to form. Which of those two timescales sounds closer to \"runs out for good\"?",
    },
    {
        "persona": "practical_encourager",
        "mode": "nudge",
        "student": "Solid liquid gas—I think I've got it.",
        "hint": "You've linked the three states. Imagine you leave a puddle on a hot pavement: which state change is the excerpt emphasizing as the water disappears into the air? What would you expect to feel near that puddle while it lasts?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "student": "What is photosynthesis?",
        "hint": "Let's sequence it: (1) light hits the leaf, (2) the excerpt says chlorophyll captures that energy, (3) carbon dioxide and water are combined to store energy in sugars. Which of those inputs must come from the air rather than the soil?",
    },
    {
        "persona": "analytical_coach",
        "mode": "balanced",
        "student": "Series and parallel circuits confuse me.",
        "hint": "The text draws a path-count distinction: one loop versus branches. In a series layout, current has a single route; in parallel, it can split. If one lamp burned out in a series string, what does the excerpt imply about the remaining path?",
    },
    {
        "persona": "analytical_coach",
        "mode": "nudge",
        "student": "Density is mass over volume, right?",
        "hint": "Your ratio is pointed the right way. If we kept mass fixed but doubled volume only, how would the excerpt predict the density value to move—up or down? What lab observation would match that shift?",
    },
    {
        "persona": "curious_explorer",
        "mode": "scaffold",
        "student": "Why do living things need nutrition?",
        "hint": "Here's one clue from the reading: living things take in materials they can't stay alive without. Nutrition in the excerpt isn't just \"eating for fun\"—it's tied to fueling growth and repair. What do you think happens to an organism that stops taking in those materials?",
    },
    {
        "persona": "curious_explorer",
        "mode": "balanced",
        "student": "Acids and bases feel like opposites.",
        "hint": "You're sensing a pairing the text sets up. The passage links acids and bases through how they react with indicators—not through being random opposites. If an indicator turned one color in lemon juice, what would the excerpt expect when a base is added slowly?",
    },
    {
        "persona": "curious_explorer",
        "mode": "nudge",
        "student": "Refraction is when light bends.",
        "hint": "Bending is the visible part—but the excerpt ties it to speed changes between media. Suppose light traveled from air into much denser water: would the ray hug the normal more or drift farther from it, according to the passage's logic?",
    },
    {
        "persona": "practical_encourager",
        "mode": "scaffold",
        "student": "I can't tell vertebrates from invertebrates.",
        "hint": "Picture a backbone like a central tent pole inside some animals but missing in others—the reading uses that internal support to split groups. Worms and insects fall on one side of that split in the excerpt; fish and birds on the other. Where would a spider land, based on that pole idea?",
    },
    {
        "persona": "analytical_coach",
        "mode": "balanced",
        "student": "Monocots vs dicots?",
        "hint": "The text contrasts seed-leaf count and vein patterns. Monocots show parallel veins in the passage's plant examples; dicots show net-like veins. If you only had a leaf drawing, which vein pattern would you measure first?",
    },
    {
        "persona": "curious_explorer",
        "mode": "nudge",
        "student": "Sound needs a medium—I remember that.",
        "hint": "Right—the excerpt stresses that vacuum gaps block sound transfer. What if an astronaut tapped helmet to helmet with no air between—would the vibration still have a material path, according to the text's rule?",
    },
    {
        "persona": "analytical_coach",
        "mode": "scaffold",
        "student": "Earth's layers are confusing.",
        "hint": "Work outside-in as the reading does: crust, then mantle, then core. The excerpt gives one property per layer—thickness or state. Which layer does the text place directly under the crust you stand on?",
    },
    {
        "persona": "practical_encourager",
        "mode": "nudge",
        "student": "Evaporation and boiling—same thing?",
        "hint": "They're related but the passage treats them at different scales. Boiling hits the whole liquid at a set temperature; evaporation can happen at the surface more quietly. On a windy day at the lake, which process would you notice first without a thermometer?",
    },
    {
        "persona": "curious_explorer",
        "mode": "balanced",
        "student": "What carries oxygen in blood?",
        "hint": "The reading names a specific component in red blood cells that binds oxygen—not the plasma alone. If that component were missing, which function in the excerpt's circulatory description would break first?",
    },
]

_default_bkt: Optional[ScienceBKT] = None
_DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
_frustration_state: dict[tuple[str, str], "FrustrationSignal"] = {}
_last_resolved_topic_by_user: dict[str, str] = {}

# Extra student phrasing aliases layered on top of syllabus keywords (all grades).
_STUDENT_TOPIC_ALIASES: dict[str, list[str]] = {
    "G6_S1_ORG_CHARS": [
        "living thing", "non living", "alive", "not alive", "grow", "breathe",
        "reproduce", "reproduction", "respond", "sensitive",
    ],
    "G7_S1_PLA_CLASSIF": ["monocot", "dicot", "monocots", "dicots"],
    "G8_S3_PHO_PROCESS": ["photosynthesis", "chlorophyll", "glucose"],
    "G9_S3_LIG_REFRAC": ["refraction", "refract", "critical angle"],
    "G9_S4_SOU_PROPAG": ["sound wave", "frequency", "amplitude", "pitch"],
}


@dataclass
class FrustrationSignal:
    """Latest engagement signal used to adapt tutor tone."""

    frustration_score: float
    level: Literal["low", "medium", "high"]
    source: str = "engagement_module"


def upsert_frustration_signal(
    user_id: str,
    topic_id: str,
    frustration_score: float,
    *,
    source: str = "engagement_module",
) -> FrustrationSignal:
    """
    Store the latest frustration cue for a user+topic.

    ``frustration_score`` is clamped to [0, 1] and mapped to:
    - low    : < 0.34
    - medium : 0.34..0.66
    - high   : > 0.66
    """
    score = max(0.0, min(1.0, float(frustration_score)))
    if score > 0.66:
        level: Literal["low", "medium", "high"] = "high"
    elif score >= 0.34:
        level = "medium"
    else:
        level = "low"
    signal = FrustrationSignal(frustration_score=score, level=level, source=source)
    _frustration_state[(str(user_id), str(topic_id))] = signal
    return signal


def _get_frustration_signal(user_id: str, topic_id: str) -> Optional[FrustrationSignal]:
    return _frustration_state.get((str(user_id), str(topic_id)))


def _tone_guidance_from_frustration(signal: Optional[FrustrationSignal]) -> str:
    if signal is None:
        return (
            "No external frustration signal is available for this turn. Keep your normal "
            "warm, concise Socratic tone."
        )
    if signal.level == "high":
        return (
            "Frustration signal is HIGH — apply these tone rules even where they relax the "
            "usual correction-first *shape* (still be textbook-accurate and Socratic, no full solutions):\n"
            "- Open with brief reassurance or empathy for confusion; normalize not knowing.\n"
            "- Do NOT open by quoting the student only to contrast or contradict (avoid "
            "'You said \"...\", but...' / 'You said X, but earlier...').\n"
            "- Do not stack reminders about past mistakes or prior turns; one gentle fix, then move on.\n"
            "- Use short sentences; one small idea; exactly ONE very easy next-step or yes/no question.\n"
            "- If they say 'I don't know' / 'no idea', answer with warmth first—never imply they should "
            "already know the answer."
        )
    if signal.level == "medium":
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
        _default_bkt = ScienceBKT(data_path="synthetic_logs.csv")
        _default_bkt.initialize_skills()
    return _default_bkt


def get_shared_bkt_engine() -> ScienceBKT:
    """
    Shared ``ScienceBKT`` used by tutor hints and the assessment API.

    Keeps one ``predict_update`` / ``student_state`` path per ``(user_id, skill)``.
    """
    return _get_default_bkt()


def _make_llm_client() -> tuple[Any, str]:
    """Return (ChatGroq client, model_name)."""
    load_dotenv(_ENV_PATH)
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it to your .env file."
        )
    model = (
        os.environ.get("GROQ_MODEL_NAME", _DEFAULT_GROQ_MODEL).strip()
        or _DEFAULT_GROQ_MODEL
    )
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
    """How chat turns update BKT; default ``strict`` to avoid falsely rising mastery."""
    load_dotenv(_ENV_PATH)
    raw = (os.environ.get("TUTOR_BKT_POLICY") or "strict").strip().lower()
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


def _resolve_persona_id(persona_id: Optional[str], user_id: str) -> str:
    """
    Resolve active persona for this turn.

    Priority: client ``persona_id`` → ``TUTOR_DEFAULT_PERSONA`` env → random rotation.
    """
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

    # Random per turn when client does not pin a persona.
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
        f"Your science authority is ONLY the retrieved textbook excerpts in the user message "
        f"(collection ``science_syllabus_g6_g9`` — official Grade 6–9 syllabus PDFs). "
        f"If the student's answer contradicts those excerpts, gently redirect using textbook "
        f"wording—not the student's mistaken labels.\n\n"
        f"{_SOCRATIC_GUARDRAILS}\n\n"
        f"--- Active persona × mastery configuration (9-state matrix cell) ---\n"
        f"{state_config}\n\n"
        f"--- Conversational continuity ---\n"
        f"- THREAD: If a recent transcript is included, the student's latest message often "
        f"answers your previous question. Acknowledge that answer before scaffolding further.\n"
        f"- MEMORY: Paraphrase a concrete phrase from their latest message so your reply "
        f"clearly responds to their words.\n"
        f"- FIGURES: Do not name figures, diagrams, exercises, or tables unless you instantly "
        f"follow with one plain-language sentence supported by the excerpts.\n"
        f"- SENTIMENT ADAPTATION: {tone_guidance}\n"
        f"  When frustration is high, soften delivery while still correcting misconceptions "
        f"and staying grounded in excerpts.\n\n"
        f"--- Correction-first protocol ---\n"
        f"If their science content is wrong relative to the excerpts:\n"
        f"  1) Brief validation of effort or intent (vary phrasing—no canned praise headers).\n"
        f"  2) Gentle correction via analogy or contrast aligned with the textbook.\n"
        f"  3) Exactly ONE follow-up question.\n"
        f"If substantially correct, validate briefly and bridge before your one question.\n\n"
        f"--- Few-shot reference conversations (study style, not facts) ---\n"
        f"These show how each persona responds across BKT modes without mechanical openers. "
        f"Do NOT copy their science content unless your retrieved excerpts support it.\n\n"
        f"{few_shots}\n\n"
        f"--- interaction_score (JSON field only; never shown in hint_text) ---\n"
        f"Set \"interaction_score\" from 0.0 to 1.0 for how well their **latest** answer matches "
        f"correct science per the retrieved excerpts. Be calibrated: wrong/vague usually ≤0.35; "
        f"major misconception ≤0.25; only clearly correct ≥0.78.\n"
        f"  • 0.0–0.35: wrong, vague, or major misconception\n"
        f"  • 0.36–0.77: partial / uncertain (not mastered)\n"
        f"  • 0.78–1.0: clearly correct and excerpt-aligned\n\n"
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


def _score_text_for_topic(text: str, topic_id: str) -> int:
    """Keyword + boost phrase scoring for one topic against normalized student text."""
    low = text.lower()
    words = set(re.sub(r"[^\w\s]", " ", low).split())
    score = 0
    keywords = list(_TOPIC_KEYWORDS.get(topic_id, []))
    keywords.extend(_STUDENT_TOPIC_ALIASES.get(topic_id, []))
    boost = _TOPIC_QUERY_BOOST.get(topic_id, "")
    if boost:
        keywords.append(boost.lower())

    for kw in keywords:
        kw_low = kw.lower().strip()
        if not kw_low:
            continue
        if kw_low in low:
            score += low.count(kw_low) + 2
            continue
        for w in words:
            if len(w) < 4 or len(kw_low) < 4:
                continue
            if w.startswith(kw_low[:4]) or kw_low.startswith(w[:4]):
                score += 1
                break
    return score


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
    fallback_topic_id: str = "G6_S1_ORG_CHARS",
) -> str:
    """
    Infer topic_id from natural language using the expanded ``_TOPIC_KEYWORDS`` catalog.

    Scores the latest student message; for short follow-ups (e.g. \"why?\", \"yes\"),
    also scores against the most recent prior user turn.
    """
    text = student_answer.strip().lower()
    if not text:
        return fallback_topic_id

    text = re.sub(r"[^\w\s]", " ", text)
    scoring_segments = [text]
    prior = _prior_user_message(conversation_history)
    if prior and len(text.split()) <= 4:
        scoring_segments.append(re.sub(r"[^\w\s]", " ", prior.strip().lower()))

    best_topic = fallback_topic_id
    best_score = 0
    for topic_id in _TOPIC_KEYWORDS:
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

    Dialogue mastery updates follow ``TUTOR_BKT_POLICY`` (default ``strict``).
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
        ``curious_explorer``). If omitted, server picks ``TUTOR_DEFAULT_PERSONA`` or
        rotates randomly each turn.
    """
    # Ensure .env variables (including HF_TOKEN / GROQ_API_KEY) are available
    # before retrieval and model calls.
    load_dotenv(_ENV_PATH)

    engine = bkt or _get_default_bkt()
    mastery_before = float(engine.get_current_mastery_probability(user_id, topic_id))
    kb = retrieve_context(topic_id, k=context_k)
    facts = (kb.get("facts_text") or "").strip()
    source_summary = _retrieval_source_summary(kb)
    mode = _hint_mode(mastery_before)
    resolved_persona = _resolve_persona_id(persona_id, user_id)
    persona_label = _PERSONA_LABELS[resolved_persona]
    frustration_signal = _get_frustration_signal(user_id, topic_id)
    tone_guidance = _tone_guidance_from_frustration(frustration_signal)

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
        f"frustration_signal_level: {frustration_signal.level if frustration_signal else 'unknown'}\n"
        f"frustration_signal_score: "
        f"{frustration_signal.frustration_score if frustration_signal else 'unknown'}\n\n"
        f"{thread_prefix}"
        f"Retrieved textbook excerpts ({source_summary}; may be partial):\n"
        f"{facts if facts else '[no excerpts retrieved]'}\n\n"
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
            "frustration_level_used": frustration_signal.level if frustration_signal else None,
            "frustration_score_used": (
                frustration_signal.frustration_score if frustration_signal else None
            ),
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
        "frustration_level_used": frustration_signal.level if frustration_signal else None,
        "frustration_score_used": (
            frustration_signal.frustration_score if frustration_signal else None
        ),
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
) -> dict[str, Any]:
    """
    Generate a hint when only free-text question/answer is provided.

    If topic_id is omitted, infer it from question keywords each turn.
    When the inferred topic changes, prior chat history is not sent to the LLM.
    """
    resolved_topic = topic_id or infer_topic_id_from_question(
        student_answer,
        conversation_history=conversation_history,
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
    result["topic_changed"] = topic_changed
    result["history_turns_sent"] = len(scoped_history or [])
    return result


__all__ = [
    "generate_socratic_hint",
    "generate_socratic_hint_auto_topic",
    "get_shared_bkt_engine",
    "infer_topic_id_from_question",
    "upsert_frustration_signal",
]
