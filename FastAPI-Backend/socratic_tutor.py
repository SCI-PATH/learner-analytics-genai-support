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
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from bkt_engine import ScienceBKT
from knowledge_base import _TOPIC_KEYWORDS, retrieve_context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = PROJECT_ROOT / ".env"

_default_bkt: Optional[ScienceBKT] = None
_DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
_frustration_state: dict[tuple[str, str], "FrustrationSignal"] = {}


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


def _hint_mode(mastery: float) -> Literal["scaffold", "balanced", "nudge"]:
    if mastery < 0.5:
        return "scaffold"
    if mastery > 0.8:
        return "nudge"
    return "balanced"


def _system_prompt(
    mode: Literal["scaffold", "balanced", "nudge"],
    tone_guidance: str,
) -> str:
    textbook = "science G-6 E (1).pdf"
    mode_block = {
        "scaffold": (
            "MASTERY MODE: SCAFFOLD (estimated P(L) < 0.5). Assume fragile understanding.\n"
            "- Teach through at least ONE vivid everyday analogy (e.g. water pipes, highway/bridge, "
            "kitchen tools, batteries, cooking) that is NOT already in the retrieved excerpt list "
            "of lab materials unless you blend both.\n"
            "- Explain enough concrete logic (~half to two thirds of hint_text) that the student "
            "can sense how two ideas might differ **before** the question; avoid meta questions "
            "like \"Does the textbook say they are identical?\"\n"
            "- End with exactly ONE inviting question toward a single small distinction they can "
            "try in plain words."
        ),
        "balanced": (
            "MASTERY MODE: BALANCED (0.5 ≤ estimated P(L) ≤ 0.8). Assume partial mastery.\n"
            "- Keep validation brief; prioritize one crisp contrast or definition split aligned with "
            "the excerpts (e.g. if two terms were asked about, explicitly relate **both** to the "
            "science idea in one or two sentences).\n"
            "- Prefer a pinpoint question that checks discrimination (same vs different, or which "
            "situation fits which term)—not a long scenario unless very short.\n"
            "- You may lightly reference framing the textbook uses, but avoid long exploratory "
            "rambles; skip counterfactual \"what would happen if\" hooks (reserve those for NUDGE)."
        ),
        "nudge": (
            "MASTERY MODE: NUDGE (estimated P(L) > 0.8). Assume the core idea is mostly in place.\n"
            "- Do NOT re-teach basics or long analogy chains; at most one short sentence of recap.\n"
            "- Close with ONE counterfactual or mini-scenario (\"What would happen if …?\", "
            "\"Suppose you … then what changes?\") so they **transfer** the distinction to a new "
            "case/tool/situation. The final sentence should be clearly hypothetical or comparative."
        ),
    }[mode]

    return (
        f"You are a Grade 6–9 science tutor using a state-aware Socratic method. Your science "
        f"authority is ONLY the retrieved excerpts from the textbook **{textbook}** (shown in "
        f"the user message). If the student's answer contradicts those excerpts, gently correct "
        f"using the textbook's definitions and wording priority—not the student's mistaken labels "
        f"(e.g. confusing energy *forms* with energy *sources*).\n\n"
        f"NO DIRECT SOLUTIONS: Never give the full final answer, full numeric result, or a "
        f"complete worked solution. Scaffolding is allowed.\n\n"
        f"--- Variable validation and tone ---\n"
        f"- NO REPETITION: Do not open with the phrase \"That's a great start.\" Rotate authentic "
        f"openers (e.g. \"You're on the right track!\", \"I see what you're getting at!\", "
        f"\"That's a clever way to put it!\", \"Nice—tell me more about that part.\"). "
        f"Vary phrasing across turns.\n"
        f"- CONVERSATIONAL THREAD: If a recent conversation transcript is included, assume the "
        f"student's latest message often **answers your previous question**. Acknowledge that answer "
        f"explicitly before teaching further; do **not** treat it as an unrelated new question.\n\n"
        f"- CONVERSATIONAL MEMORY: Quote or paraphrase a concrete phrase from the student's latest "
        f"message before you move on, so your reply clearly responds to *their* words.\n\n"
        f"- TEXTBOOK GROUNDING: Do **not** name figures, diagrams, exercises, tables, or "
        f"\"Example X.X\" unless you instantly follow with **one plain-language sentence** of what "
        f"that part says, using wording supported by the retrieved excerpts shown below.\n\n"
        f"- BREVITY: Keep hint_text concise (preferably ≤120 words), short paragraphs.\n\n"
        f"- SENTIMENT ADAPTATION: {tone_guidance}\n\n"
        f"If sentiment rules mention HIGH frustration, let them govern *how* you open and how "
        f"sharply you contrast the student's words—while still correcting misconceptions softly "
        f"and staying grounded in the textbook excerpts.\n\n"
        f"--- Correction-first protocol ---\n"
        f"If their science content is wrong or reflects a misconception relative to the "
        f"textbook excerpts, use a **correction sandwich** in order:\n"
        f"  1) Brief validation (effort or intent).\n"
        f"  2) Gentle correction using a simple analogy or plain-language contrast aligned with "
        f"the textbook.\n"
        f"  3) Exactly ONE follow-up question.\n"
        f"If they are substantially correct, you may skip heavy correction but still validate and "
        f"bridge before your one question.\n\n"
        f"{mode_block}\n\n"
        f"--- interaction_score (for the JSON field only; not shown in hint_text) ---\n"
        f"Set \"interaction_score\" from 0.0 to 1.0 reflecting how well their **latest** answer "
        f"matches correct science per {textbook}. Be **calibrated**: wrong or clearly confused "
        f"answers should usually be **≤0.35**; major misconception **≤0.25**; only strong, clearly "
        f"correct answers **≥0.78**.\n"
        f"  • 0.0–0.35: wrong, vague, or major misconception\n"
        f"  • 0.36–0.77: partial / uncertain / needs substantial help (not \"mastered\")\n"
        f"  • 0.78–1.0: clearly correct and well aligned with the excerpts\n\n"
        f"--- OUTPUT FORMAT (mandatory) ---\n"
        f"Return ONLY a single JSON object (no markdown code fences, no commentary) with exactly "
        f'two keys: "hint_text" (string, ≤120 words for the student) and "interaction_score" '
        f"(number). Example: "
        f'{{"hint_text":"...","interaction_score":0.55}}\n'
        f"If ``interaction_score`` is missing or not a number, the server will skip the "
        f"dialogue-derived mastery logic for this turn—always include a valid number.\n"
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


def infer_topic_id_from_question(
    student_answer: str,
    *,
    fallback_topic_id: str = "G6_S1_ORG_CHARS",
) -> str:
    """
    Infer the most likely topic_id using keyword overlap against syllabus topic keywords.

    This is intended for API calls where only question text is provided.
    """
    text = student_answer.strip().lower()
    if not text:
        return fallback_topic_id

    # Normalize punctuation so phrase matching is less brittle.
    text = re.sub(r"[^\w\s]", " ", text)
    words = set(text.split())

    best_topic = fallback_topic_id
    best_score = 0

    # Extra aliases for common Grade-6 biology wording used by students.
    biology_aliases = {
        "G6_S1_ORG_CHARS": [
            "living thing",
            "non living",
            "alive",
            "not alive",
            "grow",
            "breath",
            "breathe",
            "reproduce",
            "reproduction",
            "respond",
            "sensitive",
        ]
    }

    for topic_id, keywords in _TOPIC_KEYWORDS.items():
        score = 0
        all_keywords = list(keywords) + biology_aliases.get(topic_id, [])
        for kw in all_keywords:
            kw_low = kw.lower()
            if kw_low in text:
                score += text.count(kw_low) + 2
                continue

            # Lightweight fuzzy token match:
            # if any student word starts with the keyword root (or vice versa),
            # award a small score to reduce misses like "reproduce" vs "reproduction".
            for w in words:
                if len(w) < 4:
                    continue
                if w.startswith(kw_low[:4]) or kw_low.startswith(w[:4]):
                    score += 1
                    break
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
) -> dict[str, Any]:
    """
    Combine BKT mastery, local RAG context, and an LLM to produce a Socratic hint.

    Dialogue mastery updates follow ``TUTOR_BKT_POLICY`` (default ``strict``).
    Missing or invalid ``interaction_score`` → no BKT update that turn.

    Parameters
    ----------
    user_id, topic_id :
        Passed through to the learner model and retriever (topic_id must match log skill ids, e.g. G6_...).
    student_answer :
        The learner's latest free-text response.
    conversation_history :
        Prior transcript as ``[{"role":"user"|"assistant","content":str}]`` excluding this latest line.
    bkt :
        Optional shared ScienceBKT instance; otherwise a module-level default engine is used.
    context_k :
        Number of syllabus chunks to retrieve.
    """
    # Ensure .env variables (including HF_TOKEN / GROQ_API_KEY) are available
    # before retrieval and model calls.
    load_dotenv(_ENV_PATH)

    engine = bkt or _get_default_bkt()
    mastery_before = float(engine.get_current_mastery_probability(user_id, topic_id))
    kb = retrieve_context(topic_id, k=context_k)
    facts = (kb.get("facts_text") or "").strip()
    mode = _hint_mode(mastery_before)
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
        f"hint_mode: {mode}\n\n"
        f"frustration_signal_level: {frustration_signal.level if frustration_signal else 'unknown'}\n"
        f"frustration_signal_score: "
        f"{frustration_signal.frustration_score if frustration_signal else 'unknown'}\n\n"
        f"{thread_prefix}"
        f"Textbook excerpts from science G-6 E (1).pdf (retrieved chunks; may be partial):\n"
        f"{facts if facts else '[no excerpts retrieved]'}\n\n"
        f"Student's **latest** message (verbatim; reply to Tutor above if answering a question):\n"
        f"{student_answer.strip() or '[empty]'}\n"
    )

    try:
        client, model = _make_llm_client()

        def _invoke_once() -> tuple[str, Optional[float], Optional[str]]:
            response = client.invoke(
                [
                    SystemMessage(content=_system_prompt(mode, tone_guidance)),
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
) -> dict[str, Any]:
    """
    Generate a hint when only free-text question/answer is provided.

    If topic_id is omitted, infer it from question keywords.
    """
    resolved_topic = topic_id or infer_topic_id_from_question(student_answer)
    result = generate_socratic_hint(
        user_id=user_id,
        topic_id=resolved_topic,
        student_answer=student_answer,
        conversation_history=conversation_history,
        bkt=bkt,
        context_k=context_k,
    )
    result["topic_id_inferred"] = topic_id is None
    result["topic_id_resolved"] = resolved_topic
    return result


__all__ = [
    "generate_socratic_hint",
    "generate_socratic_hint_auto_topic",
    "get_shared_bkt_engine",
    "infer_topic_id_from_question",
    "upsert_frustration_signal",
]
