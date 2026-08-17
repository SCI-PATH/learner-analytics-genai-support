# Phase 2 Features — Implemented So Far

This document describes the **Phase 2 features already delivered** in the Learner Analytics & GenAI Support component. It focuses on five completed workstreams:

1. **Grade 6–9 textbook ingestion** (scaled RAG knowledge base)
2. **Automated Per-Turn Topic Routing Engine**
3. **Multi-Persona Socratic Scaffolding Engine** (3 personas × 3 BKT hint modes)
4. **Frustration Tone Adaptation v2** (decayed affective tracking + chat heuristics)
5. **Question Engine assessment integration + Misconception Cloud** (live distractor labels)

For the broader Phase 2 roadmap (PFA, evaluation metrics, production hardening), see [`PHASE2.md`](../PHASE2.md).

---

## Overview

Phase 1 established BKT mastery tracking, a Socratic RAG tutor over Grade 6 science content, frustration-aware tone, and a teacher dashboard.

Phase 2 (so far) expands that baseline so the tutor can:

- ground answers across the **full Grades 6–9** science syllabus,
- **detect the lesson automatically** each chat turn (no manual `topic_id` from the student),
- vary coaching style via **three distinct tutor personas**, still constrained by Socratic and textbook-grounding rules,
- adapt **tone and persona selection** from time-decayed frustration signals (external engagement cues + internal chat heuristics), with **zero impact on BKT mastery**.

| Feature | Primary files | Status |
|---------|---------------|--------|
| G6–G9 syllabus RAG | `FastAPI-Backend/knowledge_base.py`, `Data/Syllabi/` | Implemented |
| Auto topic routing | `FastAPI-Backend/socratic_tutor.py`, `main.py`, `Streamlit-UIs/tutor-chatbot.py` | Implemented |
| Multi-persona scaffolding | `FastAPI-Backend/socratic_tutor.py`, `main.py`, tutor chatbot UI | Implemented |
| Frustration tone v2 | `FastAPI-Backend/socratic_tutor.py`, `main.py`, `interaction_logs.json` | Implemented |
| High-density teacher dashboard | `Streamlit-UIs/teacher_dashboard.py` | Implemented |
| Question Engine assessment ingest + Misconception Cloud | `FastAPI-Backend/main.py`, teacher dashboard | Implemented |

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

## 4. Frustration Tone Adaptation v2 (Epic 7)

### Goal

Make sentiment-aware tutoring **more realistic and robust** when Component 3 (Engagement) sends frustration cues—or when the student’s own chat text signals confusion. Frustration affects **tone guidance and persona nudging only**; it never updates BKT `P(L)`.

### Story 1 — Signal lifecycle (decay & step-down)

**`FrustrationSignal`** (in `socratic_tutor.py`) now stores:

| Field | Purpose |
|-------|---------|
| `frustration_score` | Raw external score from engagement module (0.0–1.0) |
| `level` | `low` / `medium` / `high` band |
| `source` | Producer tag (e.g. `engagement_module_v1`) |
| `recorded_at` | UTC timestamp for exponential decay |

**Exponential decay** on external cues:

```text
effective_score = raw × exp(-age_seconds / τ)
```

- **τ (tau)** = **10 minutes** (600 s)
- **Floor** = **0.2** — if effective score drops below this, the external cue is treated as **expired** (no active signal)

**Post-hint consumption** (after each tutor turn):

| Condition | Action |
|-----------|--------|
| `interaction_score ≥ 0.78` | **Clear** frustration signal immediately (successful turn) |
| Otherwise | **Step down** one band: high → medium (0.50) → low (0.25) → clear |
| Step-down | Refreshes `recorded_at` so decay restarts from the lowered raw score |

**BKT isolation:** frustration lifecycle functions never call `predict_update`. Mastery changes only via assessment submit or policy-gated dialogue scores.

### Story 2 — Chat heuristics & fusion

**Internal heuristic:** `score_frustration_from_chat(student_answer)` scans for:

- Confusion phrases (“I don’t know”, “confused”, “stuck”, “help me”, …)
- Shouting (high ALL CAPS ratio)
- Repeated `?` or `!`
- Very short baffled replies

Returns an internal score **0.0–1.0**.

**Fusion** per turn via `resolve_frustration_for_turn()`:

| Scenario | Formula | `source_tag` |
|----------|---------|--------------|
| Valid external cue (after decay) | `0.7 × external_effective + 0.3 × internal` | `fused` |
| No / expired external cue | `100% internal` (if ≥ floor) | `internal_only` |
| Neither above floor | No active signal | `none` |

**Tone mapping** (unchanged bands on fused/effective score):

| Effective score | Level | Tutor behaviour |
|-----------------|-------|-----------------|
| &lt; 0.34 | `low` | Normal Socratic pacing |
| 0.34 – 0.66 | `medium` | Supportive, clearer, lighter jargon |
| &gt; 0.66 | `high` | Extra patient; shorter steps; gentler correction |

**Persona nudge:** when frustration is **high** and the client did not pin `persona_id`, the tutor defaults to **`practical_encourager`** (warmest persona).

### External integration

Component 3 sends cues to:

`POST /api/v1/engagement/frustration-cue`

```json
{
  "user_id": "student_demo",
  "topic_id": "G6_S8_ELE_CONDINS",
  "frustration_score": 0.92,
  "source": "engagement_module_v1"
}
```

The next tutor call for the same `(user_id, topic_id)` consumes the fused/decayed signal. Response includes frustration audit fields (see below).

Use **`POST /tutor/hint`** with an explicit `topic_id` when testing frustration, so the cue and tutor turn always align on the same lesson.

### Audit logging (thesis evaluation pipeline)

Each successful tutor turn appends metadata to repo-root **`interaction_logs.json`**:

| Field | Meaning |
|-------|---------|
| `frustration_raw` | Stored external raw score (if any) |
| `frustration_internal_score` | Chat heuristic score |
| `frustration_external_effective` | Decayed external score used in fusion |
| `effective_score` | Final score driving tone |
| `frustration_fused_score` | Same as effective (fusion output) |
| `source_tag` | `fused` \| `internal_only` \| `none` |
| `frustration_level_used` | `low` \| `medium` \| `high` \| null |
| `persona_id_used` | Persona selected for that turn |

### Quick frustration test

```powershell
# 1) High external cue
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/engagement/frustration-cue" `
-ContentType "application/json" -Body '{"user_id":"ep7_test","topic_id":"G6_S8_ELE_CONDINS","frustration_score":0.92,"source":"test"}'

# 2) Tutor turn (same user + topic)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/tutor/hint" `
-ContentType "application/json" -Body '{"user_id":"ep7_test","topic_id":"G6_S8_ELE_CONDINS","student_answer":"I dont get conductors vs insulators."}'
```

Expect `source_tag: "fused"`, `frustration_level_used: "high"`, warmer/shorter hint tone, and a new row in `interaction_logs.json`.

For **low** frustration, repeat with `"frustration_score": 0.10`. For **internal-only**, skip step 1 and use a new `user_id` with message `"I HAVE NO IDEA???"`.

---

## 5. Question Engine Integration & Misconception Cloud

### Goal

Connect Component 2 (Question Engine) to Component 4 so **formal quiz attempts** update BKT **and** feed the teacher dashboard’s **Misconception Cloud** with real misconception labels — not simulated tags from synthetic logs.

This is a **Component 4** feature: we **receive, persist, aggregate, and display** distractor analytics. Component 2 **generates and sends** `distractor_tag` / `distractor_label` when scoring wrong MCQs.

### What changed

**`POST /api/v1/assessment-submit`** now accepts the extended Question Engine payload (see [`Integrations/QuestionEngine-Integration.md`](../Integrations/QuestionEngine-Integration.md)):

| Field | Role in Component 4 |
|-------|---------------------|
| `user_id`, `topic_id`, `is_correct` | BKT mastery update (unchanged contract) |
| `question_type` | `"MCQ"` or `"SHORT_ANSWER"` — tells us how to interpret other fields |
| `distractor_tag`, `distractor_label` | Wrong MCQ error category + short misconception phrase |
| `similarity_score` | Short-answer analytics (stored; BKT still uses `is_correct`) |
| `response_time_s` | Passed into BKT `predict_update`; stored for future analytics |
| `question_id`, `subtopic_id`, `difficulty_level`, `chosen_distractor_text`, `source` | Optional audit / display fallbacks |

Each attempt is:

1. Applied to the shared BKT engine.
2. Stored in memory (`_assessment_attempts_by_user`).
3. Persisted to `live_state_events.db` and rehydrated on server startup.

### Misconception Cloud (teacher dashboard)

On **`GET /api/v1/analytics/student-profile/{user_id}`**, wrong attempts are aggregated into **`assessment_insights.most_frequent_distractor_tags`**.

**Label priority** (for each incorrect attempt):

1. `distractor_label` (preferred — what Component 2 sends)
2. `chosen_distractor_text` (truncated fallback)
3. `distractor_tag` enum (`NEAR_MISS`, `MISCONCEPTION`, `COMPLETE_MISS`)

**Data source switching:**

| Condition | `meta.distractor_source` | Dashboard behaviour |
|-----------|--------------------------|---------------------|
| At least one live wrong attempt with a label/tag/text | `question_engine_live` | Bar chart uses **real** Question Engine labels |
| No live attempts yet | `simulated_from_incorrect_attempts_in_synthetic_logs` | Falls back to deterministic tags from `synthetic_logs.csv` replay |

The teacher dashboard shows a caption indicating which source is active.

### Example payload (wrong MCQ)

```json
POST /api/v1/assessment-submit
{
  "user_id": "student_001",
  "topic_id": "G6_S8_ELE_CONDINS",
  "is_correct": false,
  "question_type": "MCQ",
  "distractor_tag": "MISCONCEPTION",
  "distractor_label": "Treats rubber as a conductor",
  "response_time_s": 12.5,
  "source": "question_engine_v1"
}
```

Response includes `assessment_fields_persisted` echoing what was stored.

### Quick test

```powershell
# 1) Submit a wrong MCQ with a distractor label
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/assessment-submit" `
  -ContentType "application/json" -Body '{"user_id":"student_001","topic_id":"G6_S8_ELE_CONDINS","is_correct":false,"question_type":"MCQ","distractor_tag":"MISCONCEPTION","distractor_label":"Treats rubber as a conductor"}'

# 2) Inspect profile — expect question_engine_live
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/analytics/student-profile/student_001?mode=live_state"
```

Expect `assessment_insights.most_frequent_distractor_tags` to count `"Treats rubber as a conductor"`. Open the teacher dashboard deep-dive for the same student to see the Misconception Cloud bar chart.

### Division of responsibility

| Component | Responsibility |
|-----------|----------------|
| **Component 2** (Question Engine) | Score attempts; on wrong MCQs, classify `distractor_tag` and write a short `distractor_label`; call `assessment-submit` after each scored item |
| **Component 4** (this repo) | Persist attempts; update BKT; aggregate label counts per learner; expose via student profile + teacher dashboard |

---

## How the pieces fit together (one chat turn)

```text
Student message
       │
       ▼
 Acknowledgment check? → graceful closure (skip RAG / BKT)
       │
       ▼
 Topic routing (infer G6–G9 topic_id)
       │
       ▼
 BKT mastery for (user, topic) → scaffold | balanced | nudge
       │
       ▼
 Frustration resolve (decay + fuse external + chat heuristic)
       │
       ▼
 Persona resolve (client / env / high-frustration nudge / random)
       │
       ▼
 RAG retrieve from science_syllabus_g6_g9
       │
       ▼
 Prompt = guardrails + 9-state cell + few-shots + curriculum notes
       │
       ▼
 Groq LLM → hint_text + interaction_score → optional BKT update
       │
       ▼
 Frustration consume (clear on success ≥0.78, else step-down)
       │
       ▼
 Log audit fields → interaction_logs.json
```

---

## Quick verification checklist

1. Rebuild / confirm Chroma collection `science_syllabus_g6_g9` exists.
2. Ask a Grade 9-style question (e.g. refraction) and confirm `topic_id_resolved` starts with `G9_`.
3. Switch mid-chat to a Grade 6 electricity question; confirm `topic_changed: true` and a new topic id.
4. Pin each persona and ask the same question; confirm tone differences without direct answer dumps.
5. Confirm response fields: `persona_id`, `persona_label`, `hint_mode`, `topic_id_resolved`.
6. Post high/low frustration cues; confirm `source_tag`, `frustration_level_used`, and tone shift on the next hint.
7. Inspect `interaction_logs.json` for `effective_score`, `source_tag`, and `persona_id_used` on tutor turns.
8. Open teacher dashboard with all 57 Excel topics; confirm horizontal scroll and red/orange/green BKT bands.
9. Post a wrong MCQ to `/api/v1/assessment-submit` with `distractor_label`; confirm student profile returns `distractor_source: question_engine_live` and the Misconception Cloud shows the label.

---

## Related docs

| Document | Purpose |
|----------|---------|
| [`PHASE2.md`](../PHASE2.md) | Full Phase 2 roadmap (planned + future work) |
| [`INTEGRATIONS.md`](../INTEGRATIONS.md) | Cross-component API contract (assessment + frustration) |
| [`Integrations/QuestionEngine-Integration.md`](../Integrations/QuestionEngine-Integration.md) | Full `assessment-submit` payload spec for Component 2 |
| [`SOCRATIC_CHATBOT.md`](../SOCRATIC_CHATBOT.md) | Tutor / chatbot behaviour overview |
| [`BKT MASTERY EXPLAINED.md`](../BKT%20MASTERY%20EXPLAINED.md) | Mastery model details |
| Root [`README.md`](../../README.md) | Run commands and repo layout |
