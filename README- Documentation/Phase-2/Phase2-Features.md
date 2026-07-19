# Phase 2 Features — Implemented So Far

This document describes the **Phase 2 features already delivered** in the Learner Analytics & GenAI Support component. It focuses on three completed workstreams:

1. **Grade 6–9 textbook ingestion** (scaled RAG knowledge base)
2. **Automated Per-Turn Topic Routing Engine**
3. **Multi-Persona Socratic Scaffolding Engine** (3 personas × 3 BKT hint modes)

For the broader Phase 2 roadmap (PFA, evaluation metrics, production hardening), see [`PHASE2.md`](../PHASE2.md).

---

## Overview

Phase 1 established BKT mastery tracking, a Socratic RAG tutor over Grade 6 science content, frustration-aware tone, and a teacher dashboard.

Phase 2 (so far) expands that baseline so the tutor can:

- ground answers across the **full Grades 6–9** science syllabus,
- **detect the lesson automatically** each chat turn (no manual `topic_id` from the student),
- vary coaching style via **three distinct tutor personas**, still constrained by Socratic and textbook-grounding rules.

| Feature | Primary files | Status |
|---------|---------------|--------|
| G6–G9 syllabus RAG | `FastAPI-Backend/knowledge_base.py`, `Data/Syllabi/` | Implemented |
| Auto topic routing | `FastAPI-Backend/socratic_tutor.py`, `main.py`, `Streamlit-UIs/tutor-chatbot.py` | Implemented |
| Multi-persona scaffolding | `FastAPI-Backend/socratic_tutor.py`, `main.py`, tutor chatbot UI | Implemented |

---

## 1. Grade 6–9 Textbook Ingestion

### What changed

The knowledge base was expanded from a Grade-6-only syllabus index to a **multi-grade corpus** covering Grades **6, 7, 8, and 9**.

**Source PDFs** (under `Data/Syllabi/`):

- `science G-6 E (1).pdf`
- `science G-7 P-I E.pdf`
- `science G8 P-I E.pdf`
- `science G-9 P-I E.pdf`

**Runtime index:**

| Setting | Value |
|---------|--------|
| Chroma directory | `.chroma_science_g6_g9/` (repo root) |
| Collection name | `science_syllabus_g6_g9` |
| Topic map | Merged skill hierarchy (`Data/Skill-Heirarchies-G6-G9.xlsx`) — **57 topic IDs** matching `G6_` … `G9_` |

### How ingestion works

1. PDFs are chunked and embedded locally (sentence-transformers).
2. Chunks are stored in Chroma with metadata such as `source_pdf`, `grade`, and `topic_id_primary`.
3. Retrieval (`retrieve_context`) uses topic keywords / query boosts so the tutor only sees excerpts relevant to the active lesson.
4. The LLM is instructed to treat these retrieved excerpts as the **only** science authority (no invented curriculum content).

### Supporting data updates

- Synthetic learner logs regenerated for G6–G9 topics (`Data/synthetic_logs.csv`).
- BKT skill initialization accepts Grade 6–9 topic IDs (`^G[6-9]`).
- Teacher dashboard topic lists load from the merged hierarchy (57 topics).

### Rebuild the index

From `FastAPI-Backend/`:

```powershell
python knowledge_base.py --rebuild
```

---

## 2. Automated Per-Turn Topic Routing Engine

### Problem it solves

Students should not need to pick a lesson code (e.g. `G6_S8_ELE_CONDINS`) before asking a question. Mid-conversation topic switches (e.g. from circuits to photosynthesis) should also be handled cleanly.

### How it works

Each turn on **`POST /tutor/hint-auto-topic`**:

1. **Infer topic** — `infer_topic_id_from_question()` scores the student’s latest message (and recent history segments) against keyword maps for all 57 topics; the highest-scoring topic wins.
2. **Scope history** — If the inferred topic **changes** from the previous turn, prior chat history is **not** sent to the LLM for that turn (avoids mixing lesson contexts).
3. **Retrieve + tutor** — RAG pulls excerpts for the resolved topic; BKT mastery for that `(user_id, topic_id)` drives hint mode (`scaffold` / `balanced` / `nudge`).
4. **Return routing diagnostics** — Response includes fields such as:
   - `topic_id_resolved`
   - `topic_id_inferred` (true when the client did not pass `topic_id`)
   - `topic_changed`
   - `history_turns_sent`

### Client experience

The Streamlit tutor (`Streamlit-UIs/tutor-chatbot.py`) uses **only** `/tutor/hint-auto-topic`. The student types free-text science questions; the sidebar shows the detected topic and hint mode after each reply.

The explicit-topic endpoint `POST /tutor/hint` still exists for integrations that already know `topic_id`.

### Design notes

- Routing is **keyword-based** (fast, offline, no extra LLM call).
- BKT state remains **per learner × topic**; switching lessons does not overwrite another topic’s mastery.
- When the lesson switches, conversation continuity for the *old* topic is intentionally dropped for the LLM prompt.

---

## 3. Multi-Persona Socratic Scaffolding Engine

### Goal

Increase conversational variety without weakening pedagogy. The tutor still:

- never gives full direct answers or textbook-style definition dumps,
- stays grounded in retrieved `science_syllabus_g6_g9` excerpts,
- ends with **one** Socratic question,
- adapts depth using BKT mastery (scaffold / balanced / nudge).

What *does* change is **how** the tutor sounds and frames guidance: three roleplaying personas, each combined with the three mastery modes into a **9-state matrix**.

### The three personas

#### 1. The Practical Encourager (`practical_encourager`)

| Aspect | Behaviour |
|--------|-----------|
| **Tone** | Warm, supportive, normalizing when a topic feels hard |
| **Style** | Real-world physics / biology metaphors (kitchen, weather, sport, plumbing, everyday materials) |
| **Best for** | Learners who need concrete anchors before abstract terms |
| **Scaffold** | Vivid everyday metaphor + enough concrete logic to sense a distinction, then one small question |
| **Balanced** | Mirror the student’s words → one crisp real-world contrast → discrimination question |
| **Nudge** | Short recap only; everyday mini-scenario (“on a walk / at home…”) for transfer |

#### 2. The Analytical Coach (`analytical_coach`)

| Aspect | Behaviour |
|--------|-----------|
| **Tone** | Precise, structured, “coach” rather than cheerleader |
| **Style** | Cause → mechanism → outcome; if/then logic; cautious “the excerpt suggests…” language |
| **Best for** | Learners who benefit from step-by-step mechanism breakdown |
| **Scaffold** | 2–3 numbered micro-steps; ask what happens first in the chain |
| **Balanced** | Side-by-side comparison of two terms/mechanisms; which condition flips the outcome? |
| **Nudge** | Change **one** variable; predict the next logical step (no basic re-teaching) |

#### 3. The Curious Explorer (`curious_explorer`)

| Aspect | Behaviour |
|--------|-----------|
| **Tone** | Wonder-driven; science treated like a mystery to investigate |
| **Style** | Clues (not labels), hypotheses, counterfactuals, open-ended curiosity prompts |
| **Best for** | Learners who engage when challenged to think “what if…?” |
| **Scaffold** | One textbook clue; withhold the label; invite a plain-language hypothesis |
| **Balanced** | Acknowledge a partial insight; open a “what if” that splits two close ideas |
| **Nudge** | Stretch to an unfamiliar case; ask what excerpt evidence would support/challenge their prediction |

### 9-state matrix (persona × BKT mode)

BKT mastery selects the **hint mode**:

| Mode | Mastery `P(L)` | Coaching intensity |
|------|----------------|--------------------|
| `scaffold` | &lt; 0.5 | More guidance, gentler entry |
| `balanced` | 0.5 – 0.8 | Short contrast / discrimination |
| `nudge` | &gt; 0.8 | Transfer / hypothetical; minimal recap |

Each cell of `_PERSONA_STATE_MATRIX` in `socratic_tutor.py` specialises how that persona behaves in that mode. Prompt compilation also embeds **15 few-shot conversation examples** showing natural variety (no canned openers like “Great job!” / “Good start!”).

### Hard guardrails (all personas)

Regardless of persona or mode:

1. **Grounding** — Science claims only from retrieved syllabus excerpts.
2. **No direct answers** — No full definitions, numeric solutions, or “the correct term is ___”.
3. **No structural dumps** — Guide the student to articulate the idea.
4. **One question** — Exactly one inviting question at the end.
5. **Brevity** — Prefer ≤ 120 words in `hint_text`.
6. **JSON output** — `{ "hint_text", "interaction_score" }` only.

### How a persona is selected

Priority order in `_resolve_persona_id()`:

1. Client payload field **`persona_id`** (optional on `/tutor/hint` and `/tutor/hint-auto-topic`)
2. Environment variable **`TUTOR_DEFAULT_PERSONA`**
3. Otherwise **random rotation** each turn among the three personas

**Allowed IDs:**

- `practical_encourager`
- `analytical_coach`
- `curious_explorer`

(Aliases such as `coach`, `encourager`, `explorer` are also accepted.)

Responses include:

- `persona_id`
- `persona_label` (e.g. `"The Analytical Coach"`)
- `hint_mode`

The Streamlit chatbot sidebar can **pin** a persona for testing or leave **auto (random per turn)**.

### Example API payload

```json
POST /tutor/hint-auto-topic
{
  "user_id": "student_demo",
  "student_answer": "What's the difference between a conductor and an insulator?",
  "persona_id": "curious_explorer"
}
```

Omit `persona_id` to let the server rotate personas automatically.

---

## How the pieces fit together (one chat turn)

```text
Student message
       │
       ▼
 Topic routing (infer G6–G9 topic_id)
       │
       ▼
 BKT mastery for (user, topic) → scaffold | balanced | nudge
       │
       ▼
 Persona resolve (client / env / random)
       │
       ▼
 RAG retrieve from science_syllabus_g6_g9
       │
       ▼
 Prompt = guardrails + 9-state cell + few-shots + excerpts
       │
       ▼
 Groq LLM → hint_text + interaction_score → optional BKT update
```

---

## Quick verification checklist

1. Rebuild / confirm Chroma collection `science_syllabus_g6_g9` exists.
2. Ask a Grade 9-style question (e.g. refraction) and confirm `topic_id_resolved` starts with `G9_`.
3. Switch mid-chat to a Grade 6 electricity question; confirm `topic_changed: true` and a new topic id.
4. Pin each persona and ask the same question; confirm tone differences without direct answer dumps.
5. Confirm response fields: `persona_id`, `persona_label`, `hint_mode`, `topic_id_resolved`.

---

## Related docs

| Document | Purpose |
|----------|---------|
| [`PHASE2.md`](../PHASE2.md) | Full Phase 2 roadmap (planned + future work) |
| [`SOCRATIC_CHATBOT.md`](../SOCRATIC_CHATBOT.md) | Tutor / chatbot behaviour overview |
| [`BKT MASTERY EXPLAINED.md`](../BKT%20MASTERY%20EXPLAINED.md) | Mastery model details |
| Root [`README.md`](../../README.md) | Run commands and repo layout |
