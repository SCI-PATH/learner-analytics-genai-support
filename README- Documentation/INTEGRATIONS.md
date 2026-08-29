# Integrations Guide — Component 4 (Learner Profile Analytics & GenAI Support)

**Audience:** teammates on Components 1–3  
**Owner of this hub:** Component 4 (IT22055262 — Liyaudeen D.H.)  
**Base URL (local):** `http://127.0.0.1:8000`  
**OpenAPI docs:** `http://127.0.0.1:8000/docs`

This document is the **integration contract** for R26-SE-003. It answers:

1. What **you send to Component 4**
2. What **you consume from Component 4**
3. Whether we must share the **same RAG / PDF chunks** (short answer: **no**)
4. Whether we must share the **same `topic_id` schema** (short answer: **yes**)

Aligned with the proposal roles in `Data/RP Proposal Documents/`:

| Component | Proposal role | Typical owner |
|-----------|---------------|---------------|
| **1** | Learning Path / Adaptive Content & Orchestration Engine | Content generation + path DAG |
| **2** | Intelligent Assessment / Question Engine | Quiz generation + DDA (IRT/RL) |
| **3** | Engagement & Motivation (NASEM-GLE) | Frustration / sentiment / gamification cues |
| **4** | **Learner Profile Analytics & GenAI Support (this repo)** | BKT mastery hub + Socratic RAG tutor + teacher analytics |

---

## 1. Mental model: one shared curriculum key, separate knowledge stores

```text
                    ┌─────────────────────────────────────┐
                    │     Shared curriculum topic_id      │
                    │  (Skill-Heirarchies-G6-G9.xlsx)      │
                    └──────────────┬──────────────────────┘
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
   Component 1               Component 2               Component 4
   Content RAG               Question RAG              Tutor RAG
   (own Chroma)              (own Chroma)              (own Chroma)
   lesson/hints              quiz items                Socratic hints
           │                       │                       │
           │                       │  assessment outcomes  │
           │                       └──────────►────────────┤
           │              Component 3                      │
           │              frustration cues ───────────────►│
           │◄──── mastery / at-risk / profile ─────────────┘
```

### Do we need to share the same RAG / PDF chunks?

**No.** Each component may chunk and embed the Grade 6–9 syllabus PDFs for its **own purpose**:

| Component | Why it chunks PDFs |
|-----------|--------------------|
| **1** | Personalized lesson explanations, analogies, content depth |
| **2** | Grounded question generation (facts → MCQs / short answers) |
| **4** | Socratic tutoring grounded in verified curriculum snippets |

You do **not** need to share Chroma collections, chunk IDs, embedding models, or chunk boundaries with Component 4. Parallel RAG is expected and healthy.

### Do we need the same `topic_id` format?

**Yes — this is the critical handshake.**

Component 4’s BKT engine, tutor routing, frustration lookup, mastery matrix, and at-risk alerts are all keyed by:

```text
(user_id, topic_id)
```

If Component 2 submits `is_correct` under a different ID than Component 1 uses for lessons (or than Component 4 uses for tutoring), mastery will **not** line up with content or quizzes.

**Ask Components 1 and 2 to adopt Component 4’s canonical `topic_id` list** (already prepared for assessment alignment — see Excel column name below).  
If someone already uses another ID scheme, maintain a **mapping table** to these IDs before calling our APIs. Do not invent silent aliases.

---

## 2. Canonical `topic_id` schema (shared contract)

**Source of truth file in this repo:**

`Data/Skill-Heirarchies-G6-G9.xlsx`

| Column | Meaning |
|--------|---------|
| Core Concept / Chapter Title | Human-readable chapter theme |
| **Topic ID (Canonical)** | **Canonical `topic_id` string** |
| Curriculum Reference | Short description of the skill |

Prefer the shareable full file: **`Data/Skill-Heirarchies-G6-G9-Full-Chapters.xlsx`**.

**Format:**

```text
G{grade}_C{chapter}_{DOMAIN_ABBREV}_{CONCEPT_ABBREV}
```

Examples:

- `G6_C8_ELE_CONDINS` — Grade 6 Chapter 8 conductors / insulators  
- `G6_C8_ELE_CIRCUITS` — Grade 6 Chapter 8 circuits  
- `G8_C11_PHO_PROCESS` — Grade 8 Chapter 11 photosynthesis  
- `G9_C14_WAV_REFRACT` — Grade 9 Chapter 14 light refraction  

**Rules for teammates:**

1. Send `topic_id` **exactly** as listed (case-sensitive, underscores, no spaces).
2. There are **128** leaf topic IDs spanning Grades **6–9** (every textbook chapter covered; 2 skills per chapter).
3. Canonical spreadsheet: **`Data/Skill-Heirarchies-G6-G9-Full-Chapters.xlsx`** (also `Skill-Heirarchies-G6-G9-UPDATED.xlsx` if the older file is open).
4. Unknown IDs cause assessment/tutor errors or appear in `unknown_topic_ids` on the mastery matrix.
5. Prefer one shared spreadsheet so Content, Questions, and Analytics stay in sync.

**Recommendation to the Question Engine owner:** yes — match **this** `topic_id` schema (the Excel already labels it for the Assessment Module). Content Generation should use the **same** IDs when tagging lessons and when telling Component 2 which topic is “active.”

---

## 3. What Component 4 expects FROM other components

### 3.1 Component 2 → Component 4 (Assessment outcomes)

**Endpoint (you call us):** `POST /api/v1/assessment-submit`  
**Purpose:** Trusted ground-truth updates to BKT mastery (quiz / puzzle correctness).

#### Required fields (current contract)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | string | **Yes** | Anonymized learner ID (same ID used across all components) |
| `topic_id` | string | **Yes** | Canonical skill ID from the shared hierarchy |
| `is_correct` | boolean | **Yes** | `true` = correct, `false` = incorrect |

#### Example request

```json
{
  "user_id": "U123",
  "topic_id": "G6_S8_ELE_CIRCUITS",
  "is_correct": true
}
```

#### Example success response

```json
{
  "success": true,
  "user_id": "U123",
  "topic_id": "G6_C8_ELE_CIRCUITS",
  "is_correct": true,
  "updated_mastery_probability": 0.71,
  "mastery_probability": 0.71,
  "mastery_category": "intermediate",
  "mastery_category_thresholds": {
    "basic": "P(L) < 0.50",
    "intermediate": "0.50 <= P(L) < 0.80",
    "advanced": "P(L) >= 0.80"
  },
  "risk_flag": false,
  "bkt_observation_label": 1,
  "label_source": "assessment"
}
```

#### Processing (what we do)

1. Map `is_correct` → BKT label `1` / `0`
2. `predict_update(user_id, topic_id, label)` on the **shared** BKT engine
3. Persist event for restart resilience
4. Return updated `P(L)` mastery, derived **`mastery_category`**, and `risk_flag`

**Read without submitting:** `GET /api/v1/mastery/{user_id}/{topic_id}` returns the same `mastery_probability` + `mastery_category` without recording a new attempt.

**Quiz start (chapter-scoped):** `POST /api/v1/quiz/bkt-snapshot` with `{ user_id, chapter_ids }`. See [`Integrations/QuestionEngine-BKT-Snapshot.md`](./Integrations/QuestionEngine-BKT-Snapshot.md). `assessment-submit` also returns a `topic_bkt` map for the active chapter(s).

#### Proposal-aligned fields we do **not** require yet (optional future)

Your proposal / assessment design may also produce:

| Field (your side) | Status on our API today |
|-------------------|-------------------------|
| Response time | Not required (ignored if sent unless we extend schema) |
| Difficulty level | Not required |
| Distractor tag / chosen wrong option | Not required (useful later for slip vs misconception analysis) |
| Question type (MCQ / short) | Not required |
| Subtopic ID | Prefer flattening to canonical `topic_id` |
| Similarity score (short answers) | Not required |

**Team ask:** keep sending at least `{user_id, topic_id, is_correct}` after each scored item (or quiz session item). If you want richer logging, tell Component 4 and we can add an optional `metadata` object without breaking the BKT path.

**Call timing:** after each scored item is ideal for live mastery; batch end-of-quiz is acceptable if every item still includes the correct `topic_id`.

---

### 3.2 Component 3 → Component 4 (Engagement / frustration cues)

**Endpoint (you call us):** `POST /api/v1/engagement/frustration-cue`  
**Purpose:** Sentiment-aware **tutor tone** only — does **not** change BKT mastery.  
**Teammate README:** [`Integrations/FrustrationCue-Engagement-Integration.md`](Integrations/FrustrationCue-Engagement-Integration.md)

Agreed UX: the in-game chatbot unlocks **after the level**, not during scored questions. Component 3 should POST the cue at **level complete / chatbot unlock**.

#### Required fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | string | **Yes** | Same learner ID as assessment / tutor |
| `topic_id` | string | **Yes** | Current lesson / quiz topic (canonical ID) |
| `frustration_score` | float `0.0–1.0` | **Yes** | Normalized frustration intensity. Values `> 1` up to `100` are treated as a 0–100 score and divided by 100. |
| `source` | string | No (default `engagement_module`) | Producer name / version |

#### Example request

```json
{
  "user_id": "U123",
  "topic_id": "G6_S8_ELE_CIRCUITS",
  "frustration_score": 0.78,
  "source": "engagement_module_v1"
}
```

#### Score → level mapping (our side)

| Score | Level | Tutor tone effect on next hint |
|-------|-------|--------------------------------|
| `< 0.34` | `low` | Normal Socratic tone |
| `0.34–0.66` | `medium` | Supportive, clearer, lighter jargon |
| `> 0.66` | `high` | Extra patient, shorter steps, gentler correction |

#### Example success response

```json
{
  "success": true,
  "user_id": "U123",
  "topic_id": "G6_S8_ELE_CIRCUITS",
  "frustration_score": 0.78,
  "frustration_level": "high",
  "source": "engagement_module_v1",
  "used_by": ["/tutor/hint", "/tutor/hint-auto-topic"]
}
```

**Team ask:** POST the level’s latest cue (including **low** scores) at **chatbot unlock**, with the same `topic_id` as the level. We store the latest cue per `(user_id, topic_id)` and consume it on the next tutor turn. Do not POST every mouse sample. Do not send Component 3’s `VERY_LOW`…`VERY_HIGH` labels — we remap to `low` / `medium` / `high`.

---

### 3.3 Component 1 → Component 4 (Content / Learning Path)

**Today:** no dedicated inbound “content packet” endpoint is required for BKT.

What Component 1 should still align on:

| Expectation | Why |
|-------------|-----|
| Same `topic_id` vocabulary | So path recommendations match mastery keys |
| Same `user_id` namespace | So profiles are joinable |
| Consume mastery / at-risk from our outbound APIs | Drive review topics / next-day path (proposal: Analytics → Learning Path) |

Optional future (not implemented yet): Component 1 could POST “session ended / active topic” events. Until then, **pull mastery** from the endpoints in §4.

---

## 4. What other components consume FROM Component 4

### 4.1 Mastery matrix (classroom / path / dashboards)

`POST /api/v1/mastery/matrix`

```json
{
  "student_ids": ["U123", "U124"],
  "topic_ids": ["G6_S8_ELE_CONDINS", "G6_S8_ELE_CIRCUITS"],
  "mode": "live_state"
}
```

| `mode` | Meaning |
|--------|---------|
| `live_state` | In-memory + rehydrated live events (assessment / tutor since process start) |
| `replay_logs` | Baseline from `Data/synthetic_logs.csv` replay |

**Returns:** `mastery_matrix[user_id][topic_id] = P(L)`, plus `unknown_topic_ids`.

**Consumers:** Component 1 (path adaptation), teachers / dashboards, optionally Component 2 for cold-start baselines.

---

### 4.2 At-risk students

`POST /api/v1/analytics/at-risk-students`

Optional filters: `student_ids`, `topic_ids`, `mode` (`live_state` | `replay_logs`).

**Returns:** learners flagged at risk for topics (BKT risk logic).

**Consumers:** Component 1 (insert review), Component 3 (motivation interventions), teachers.

---

### 4.3 Student profile (deep dive)

`GET /api/v1/analytics/student-profile/{user_id}?mode=live_state`

**Returns:** per-topic mastery, BKT parameters (`p_l`, `p_g`, `p_s`), attempt / engagement-related profile fields.

**Consumers:** Component 2 (historical baseline for IRT placement — as described in Assessment proposal), Component 1, teacher UI.

---

### 4.4 Tutor endpoints (student-facing GenAI)

These are primarily for the **student chatbot UI** (or a shell that embeds the tutor). Other components usually do not call them unless they host the chat surface.

| Endpoint | When to use |
|----------|-------------|
| `POST /tutor/hint` | Caller already knows `topic_id` |
| `POST /tutor/hint-auto-topic` | Free-text only; we infer `topic_id` each turn |

Useful request fields:

| Field | Notes |
|-------|-------|
| `user_id` | Required |
| `student_answer` | Latest student message |
| `topic_id` | Required for `/tutor/hint`; optional for auto |
| `conversation_history` | Prior turns `[{role, content}]` |
| `persona_id` | Optional: `practical_encourager` \| `analytical_coach` \| `curious_explorer` |
| `context_k` | RAG chunk count (default 4) |

Useful response fields for teammates debugging integrations:

- `topic_id_resolved`, `hint_mode`, `persona_id` / `persona_label`
- `mastery_probability_before` / `updated_mastery_probability`
- `frustration_level_used` / `frustration_score_used`
- `bkt_updated`, `socratic_loop_bypassed` (acknowledgment / “thanks” short-circuit)

---

## 5. Responsibility split (keep this clean)

| Data | Producer | Consumer | Updates BKT? | Effect |
|------|----------|----------|--------------|--------|
| Quiz correctness | Component 2 | Component 4 | **Yes (trusted)** | Mastery `P(L)` |
| Frustration score | Component 3 | Component 4 | **No** | Tutor tone only |
| Chat `interaction_score` | Component 4 (LLM) | Component 4 | Policy-gated / optional | Noisy dialogue updates |
| Mastery / at-risk | Component 4 | Components 1–3, teachers | — | Path, placement, alerts |
| Lesson / quiz PDF chunks | Each component’s own RAG | Same component | — | Grounding only |

This matches the proposal loop:

- **Assessment → Analytics** (scores / distractors conceptually; today: `is_correct`)
- **Engagement → GenAI** (frustration → patient tone)
- **Analytics → Learning Path** (mastery / risk → review topics)
- **Analytics → Teacher dashboard** (matrix / at-risk)

---

## 6. Question Engine ↔ Content Generation ↔ Component 4 (RAG clarification)

### What Component 2’s proposal says

- Component 1 sends an **active Topic ID**
- Component 2 retrieves lesson text from **its** ChromaDB and generates questions
- After the quiz, Component 2 transmits performance metrics to Component 4

### What Component 4 does independently

- Maintains **its own** Chroma collection: `science_syllabus_g6_g9` under `.chroma_science_g6_g9/`
- Retrieves snippets for Socratic tutoring only
- Does **not** depend on Component 1’s or 2’s chunk store

### Integration checklist for Content + Questions teammates

| # | Agreement | Owner |
|---|-----------|-------|
| 1 | Use shared `topic_id` list from `Skill-Heirarchies-G6-G9.xlsx` | All |
| 2 | Keep separate RAG indexes (no forced shared Chroma) | All |
| 3 | After scoring, call `POST /api/v1/assessment-submit` with `{user_id, topic_id, is_correct}` | Component 2 |
| 4 | When starting a quiz, `POST /api/v1/quiz/bkt-snapshot` with `{user_id, chapter_ids}` | Component 2 |
| 5 | When building next-day path, `POST` mastery matrix / at-risk | Component 1 |
| 6 | At level complete / chatbot unlock, `POST` frustration-cue (`FS/100`) with same `topic_id` | Component 3 |

**Bottom line for the Question Engine owner:**  
You do **not** need to share PDF chunks with Component 4. You **do** need to use the **same `topic_id` strings** Component 4 (and ideally Content) use — ask them to match this schema (or map into it before the assessment-submit call).

---

## 7. Shared identity & privacy conventions

- Prefer **anonymized** `user_id` values (proposal: no real names/emails in inter-component traffic).
- The same `user_id` must be used for assessment, frustration, tutor, and analytics pulls.
- Always pair signals with the **active lesson** `topic_id`.

---

## 8. Quick smoke tests for teammates

```http
GET /health
```

```http
POST /api/v1/quiz/bkt-snapshot
Content-Type: application/json

{ "user_id": "demo_student", "chapter_ids": ["G6_C8"] }
```

```http
POST /api/v1/assessment-submit
Content-Type: application/json

{ "user_id": "demo_student", "topic_id": "G6_S1_ORG_CHARS", "is_correct": false }
```

```http
POST /api/v1/engagement/frustration-cue
Content-Type: application/json

{
  "user_id": "demo_student",
  "topic_id": "G6_S1_ORG_CHARS",
  "frustration_score": 0.82,
  "source": "engagement_module_v1"
}
```

```http
POST /api/v1/mastery/matrix
Content-Type: application/json

{
  "student_ids": ["demo_student"],
  "topic_ids": ["G6_S1_ORG_CHARS"],
  "mode": "live_state"
}
```

---

## 9. Change control

If Components 1–2 need a new topic leaf:

1. Add it to `Data/Skill-Heirarchies-G6-G9.xlsx` (and regenerate synthetic logs / BKT skill map as needed).
2. Notify all teammates of the new `topic_id`.
3. Component 4 updates keyword maps / RAG topic boosts for tutoring.
4. Components 1–2 tag content / questions with the same ID.

Do **not** silently rename existing IDs — that breaks historical mastery trajectories.

---

## Related docs

| Doc | Use |
|-----|-----|
| [`Integrations/QuestionEngine-BKT-Snapshot.md`](./Integrations/QuestionEngine-BKT-Snapshot.md) | Quiz init snapshot + `assessment-submit` `topic_bkt` map |
| [`SOCRATIC_CHATBOT.md`](./SOCRATIC_CHATBOT.md) | Tutor behaviour |
| [`BKT MASTERY EXPLAINED.md`](./BKT%20MASTERY%20EXPLAINED.md) | What `P(L)` means |
| [`Phase-2/Phase2-Features.md`](./Phase-2/Phase2-Features.md) | G6–G9 RAG, auto-topic, personas |
| Proposal PDF | `Data/RP Proposal Documents/R26-SE-003_IT22055262_LIYAUDEEN D.H.pdf` |
