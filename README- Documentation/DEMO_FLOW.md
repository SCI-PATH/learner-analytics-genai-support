# Demo flow — central hub (FastAPI + tutor + dashboard)

Use this checklist when rehearsing or presenting your **Learner Profile / Socratic tutor** component. All URLs assume the API runs at `http://127.0.0.1:8000` unless you change it.

---

## Prerequisites

1. **Python venv** activated (project `.venv`).
2. **API server** (terminal 1):

   ```bash
   uvicorn main:app --reload
   ```

3. Optional UIs (separate terminals):

   - Socratic chat test: `streamlit run tutor-chatbot.py`
   - Teacher heatmap: `streamlit run teacher_dashboard.py`

4. **Environment:** `GROQ_API_KEY` in `.env` for tutor LLM calls.

---

## Valid topic IDs (BKT skills)

Your current `synthetic_logs.csv` includes exactly these **seven** `skill_name` / topic IDs:

- `G6_S1_ORG_CHARS`
- `G6_S1_ORG_CLASS`
- `G6_S2_MAT_PROPS`
- `G6_S2_MAT_STATES`
- `G6_S4_ENE_SOURCES`
- `G6_S8_ELE_CIRCUITS`
- `G6_S8_ELE_CONDINS`

Use only these (or extend your dataset) to avoid `unknown_topic_ids` in the mastery matrix.

Example **student IDs** from logs: `user_001` … `user_025`.

**Quick topic cheat sheet (for demos):**

| `topic_id` | Theme |
|------------|--------|
| `G6_S1_ORG_CHARS` | Living vs non-living / characteristics of life |
| `G6_S1_ORG_CLASS` | Classification of organisms |
| `G6_S2_MAT_PROPS` | Physical properties of materials |
| `G6_S2_MAT_STATES` | States of matter (solid / liquid / gas) |
| `G6_S4_ENE_SOURCES` | Energy sources and forms |
| `G6_S8_ELE_CIRCUITS` | Simple electric circuits |
| `G6_S8_ELE_CONDINS` | Conductors vs insulators |

---

## Endpoints overview (`main.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness check |
| POST | `/tutor/hint` | Tutor with explicit `topic_id` |
| POST | `/tutor/hint-auto-topic` | Tutor; optional topic inference |
| POST | `/api/v1/assessment-submit` | Ground-truth quiz outcome → BKT update |
| POST | `/api/v1/engagement/frustration-cue` | Frustration score → tone hint for next tutor turn |
| POST | `/api/v1/analytics/at-risk-students` | Student-level at-risk alerts (`live_state` / `replay_logs`) |
| POST | `/api/v1/mastery/matrix` | Classroom matrix for teacher dashboard |
| GET | `/api/v1/analytics/student-profile/{user_id}` | Learner profile with BKT, engagement, and timeline details |

---

## Recommended demo script (pick one learner + topic and stay consistent)

**Default storyline (biology — no circuits required):**

- `user_id`: `user_003`
- `topic_id`: `G6_S1_ORG_CHARS` (living vs non-living)

### Step 0 — Health

```http
GET http://127.0.0.1:8000/health
```

Expect: `{"status":"ok"}`.

### Step 1 — Simulate question engine (assessment)

**Why:** Shows integration with Component 2; updates **trusted** mastery on the same BKT state as the tutor.

```http
POST http://127.0.0.1:8000/api/v1/assessment-submit
Content-Type: application/json

{
  "user_id": "user_003",
  "topic_id": "G6_S1_ORG_CHARS",
  "is_correct": false
}
```

**Talking point:** “Quiz outcomes are binary ground truth; they feed `predict_update` directly.”

### Step 2 — Simulate engagement module (frustration)

**Why:** Shows integration with Component 3; **does not** change BKT — it only affects the **next** tutor reply’s tone for this `(user_id, topic_id)`.

```http
POST http://127.0.0.1:8000/api/v1/engagement/frustration-cue
Content-Type: application/json

{
  "user_id": "user_003",
  "topic_id": "G6_S1_ORG_CHARS",
  "frustration_score": 0.78,
  "source": "demo_engagement"
}
```

Use `0.2` for low frustration vs `0.82` for high to contrast tone.

**Talking point:** “Affective data routes separately from knowledge tracing.”

### Step 3 — Student chat (tutor)

Use Streamlit `tutor-chatbot.py` **or** curl:

```http
POST http://127.0.0.1:8000/tutor/hint-auto-topic
Content-Type: application/json

{
  "user_id": "user_003",
  "student_answer": "Is a rock alive? I thought it grows because stalactites get bigger.",
  "topic_id": "G6_S1_ORG_CHARS",
  "context_k": 4
}
```

Check JSON fields:

- `mastery_probability_before` / `updated_mastery_probability` — BKT before/after this turn (depends on `TUTOR_BKT_POLICY` and decisive `interaction_score`).
- `bkt_updated` — whether dialogue triggered `predict_update` this turn.
- `frustration_level_used` / `frustration_score_used` — sentiment cue consumed for tone (if any was stored).
- `hint_text` — Socratic reply.

**Talking point:** “Trusted mastery moves with quiz; tutor can supplement under strict dialogue policy—or not at all with `TUTOR_BKT_POLICY=quiz_only`.”

Repeat Step 3 with follow-up replies; under **strict** dialogue policy, mastery moves mainly when quiz fires or scores are extreme.

### Step 4 — Teacher dashboard (classroom view)

**Option A — Live session (matches Steps 1–3)**

In `teacher_dashboard.py`:

- Set **FastAPI Base URL** to `http://127.0.0.1:8000`.
- **Mode:** `live_state`.
- **Student IDs:** include `user_003`.
- **Topic IDs:** include `G6_S1_ORG_CHARS` plus any mix from the cheat sheet above.

Refresh after tutor/assessment calls; the heatmap reflects **in-memory** state of this API process.

**Option B — Historical baseline (no prior demo steps needed)**

- **Mode:** `replay_logs`.
- Replays `synthetic_logs.csv` through BKT for selected users/topics — good for a stable “classroom” picture independent of live chat.

**Talking point:** “Educators see aggregated P(L); green / orange / red bands match the acceptance criteria in Epic 4.”

---

## Copy-paste JSON examples (swap `user_id` / `topic_id` as needed)

### `POST /api/v1/assessment-submit`

```json
{ "user_id": "user_002", "topic_id": "G6_S2_MAT_STATES", "is_correct": true }
```

```json
{ "user_id": "user_005", "topic_id": "G6_S4_ENE_SOURCES", "is_correct": false }
```

```json
{ "user_id": "user_012", "topic_id": "G6_S8_ELE_CONDINS", "is_correct": true }
```

```json
{ "user_id": "user_007", "topic_id": "G6_S2_MAT_PROPS", "is_correct": false }
```

```json
{ "user_id": "user_015", "topic_id": "G6_S1_ORG_CLASS", "is_correct": true }
```

```json
{ "user_id": "user_020", "topic_id": "G6_S8_ELE_CIRCUITS", "is_correct": true }
```

### `POST /api/v1/engagement/frustration-cue`

```json
{ "user_id": "user_004", "topic_id": "G6_S2_MAT_STATES", "frustration_score": 0.25, "source": "engagement_demo" }
```

```json
{ "user_id": "user_004", "topic_id": "G6_S2_MAT_STATES", "frustration_score": 0.88, "source": "engagement_demo" }
```

```json
{ "user_id": "user_006", "topic_id": "G6_S4_ENE_SOURCES", "frustration_score": 0.55, "source": "watchdog_v1" }
```

```json
{ "user_id": "user_008", "topic_id": "G6_S1_ORG_CHARS", "frustration_score": 0.72, "source": "ui_session" }
```

```json
{ "user_id": "user_010", "topic_id": "G6_S8_ELE_CONDINS", "frustration_score": 0.15, "source": "mouse_model" }
```

```json
{ "user_id": "user_011", "topic_id": "G6_S2_MAT_PROPS", "frustration_score": 0.92, "source": "engagement_demo" }
```

### `POST /tutor/hint-auto-topic`

```json
{
  "user_id": "user_002",
  "student_answer": "What makes water different when it freezes versus when it boils?",
  "topic_id": "G6_S2_MAT_STATES",
  "context_k": 4
}
```

```json
{
  "user_id": "user_005",
  "student_answer": "Is sunlight the same thing as thermal energy stored in fossil fuels?",
  "topic_id": "G6_S4_ENE_SOURCES",
  "context_k": 4
}
```

```json
{
  "user_id": "user_008",
  "student_answer": "Why do we wrap wires in plastic but use metal inside?",
  "topic_id": "G6_S8_ELE_CONDINS",
  "context_k": 4
}
```

```json
{
  "user_id": "user_014",
  "student_answer": "How do hardness and elasticity help engineers pick materials for a bridge?",
  "topic_id": "G6_S2_MAT_PROPS",
  "context_k": 4
}
```

```json
{
  "user_id": "user_016",
  "student_answer": "Why aren't fungi grouped with plants anymore?",
  "topic_id": "G6_S1_ORG_CLASS",
  "context_k": 4
}
```

```json
{
  "user_id": "user_018",
  "student_answer": "If I unplug the laptop, why does my torch still shine?",
  "topic_id": "G6_S8_ELE_CIRCUITS",
  "context_k": 4
}
```

```json
{
  "user_id": "user_009",
  "student_answer": "My updated answer: photosynthesis releases oxygen.",
  "topic_id": "G6_S1_ORG_CHARS",
  "conversation_history": [
    { "role": "assistant", "content": "What gas do plants usually release during photosynthesis?" },
    { "role": "user", "content": "Um... is it nitrogen?" }
  ],
  "context_k": 4
}
```

### `POST /tutor/hint` (explicit topic only)

```json
{
  "user_id": "user_013",
  "topic_id": "G6_S1_ORG_CHARS",
  "student_answer": "Growth means something gets bigger — so crystals must be alive, right?",
  "context_k": 4
}
```

```json
{
  "user_id": "user_017",
  "topic_id": "G6_S4_ENE_SOURCES",
  "student_answer": "Batteries make electricity forever until you throw them away.",
  "context_k": 6
}
```

(Optional: add `"conversation_history": [ ... ]` the same shape as hint-auto-topic.)

### `POST /api/v1/mastery/matrix`

```json
{
  "student_ids": ["user_001", "user_004", "user_009"],
  "topic_ids": ["G6_S1_ORG_CHARS", "G6_S4_ENE_SOURCES", "G6_S2_MAT_STATES"],
  "mode": "live_state"
}
```

```json
{
  "student_ids": ["user_002", "user_003"],
  "topic_ids": ["G6_S2_MAT_PROPS", "G6_S8_ELE_CONDINS"],
  "mode": "replay_logs"
}
```

```json
{
  "student_ids": ["user_011", "user_012", "user_013", "user_014"],
  "topic_ids": [
    "G6_S1_ORG_CHARS",
    "G6_S1_ORG_CLASS",
    "G6_S2_MAT_PROPS",
    "G6_S2_MAT_STATES",
    "G6_S4_ENE_SOURCES",
    "G6_S8_ELE_CIRCUITS",
    "G6_S8_ELE_CONDINS"
  ],
  "mode": "replay_logs"
}
```

---

## Quick curl (PowerShell-friendly)

Replace `-Body` with any JSON from the examples above.

```powershell
# Assessment — organisms (living things)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/assessment-submit" `
  -ContentType "application/json" `
  -Body '{"user_id":"user_003","topic_id":"G6_S1_ORG_CHARS","is_correct":false}'

# Frustration — states of matter
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/engagement/frustration-cue" `
  -ContentType "application/json" `
  -Body '{"user_id":"user_004","topic_id":"G6_S2_MAT_STATES","frustration_score":0.84,"source":"demo"}'

# Tutor — energy sources
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/tutor/hint-auto-topic" `
  -ContentType "application/json" `
  -Body '{"user_id":"user_005","student_answer":"Difference between renewable and non-renewable?","topic_id":"G6_S4_ENE_SOURCES","context_k":4}'

# Mastery matrix (live — mixed topics)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/mastery/matrix" `
  -ContentType "application/json" `
  -Body '{"student_ids":["user_002","user_005"],"topic_ids":["G6_S8_ELE_CONDINS","G6_S4_ENE_SOURCES","G6_S2_MAT_STATES"],"mode":"live_state"}'
```

---

## Pitfalls (mention if asked)

1. **Restarting uvicorn** no longer fully wipes live state: assessment/frustration/chat events are persisted and rehydrated at startup. If persistence files are removed/corrupted, re-run demo steps.
2. **Wrong `topic_id`** — assessment/tutor may error; matrix returns `unknown_topic_ids` for invalid skills.
3. **Tutor without `interaction_score`** — hint still returns, but `bkt_updated` is false for that turn.
4. **`TUTOR_BKT_POLICY`** — default **strict**: mid-range scores often **skip** mastery updates even when hints look fine; **`quiz_only`** turns off chat-driven BKT entirely; **`legacy`** is more lenient and can inflate mastery.

---

## One-minute “why these endpoints” pitch

- **Assessment submit:** authoritative labels from the question engine → mastery.
- **Frustration cue:** engagement telemetry → empathetic tone, not a substitute for correctness.
- **Tutor:** dialogue + RAG; optional dialogue BKT governed by **`TUTOR_BKT_POLICY`** (`strict` / `quiz_only` / `legacy`) plus LLM scores.
- **Mastery matrix:** teacher-facing aggregation of the same learner model.

This matches the separation of concerns in your proposal: cognitive state vs affective state vs pedagogy.
