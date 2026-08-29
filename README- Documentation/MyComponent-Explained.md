# My Component Explained — Demo Briefing

**Component 4: Learner Profile Analytics & GenAI Support**

This is your one-page briefing for demos: what this component owns, how the Socratic chatbot works, how BKT mastery is calculated, and how the teacher dashboard decides who is at risk.

For deeper detail, see also:
- [`SOCRATIC_CHATBOT.md`](./SOCRATIC_CHATBOT.md)
- [`BKT MASTERY EXPLAINED.md`](./BKT%20MASTERY%20EXPLAINED.md)
- [`TEACHER_DASHBOARD.md`](./TEACHER_DASHBOARD.md)
- [`INTEGRATIONS.md`](./INTEGRATIONS.md)

---

## 1. What this component is

You are the **central intelligence hub** of the SCI-PATH ecosystem.

| You own | Other components use you for |
|---------|------------------------------|
| BKT mastery model (per student × topic) | Updated mastery after quizzes (Question Engine) |
| Socratic RAG tutor (chatbot) | Frustration cues change tutor **tone only** (Engagement) |
| Teacher analytics dashboard | Shared `topic_id`s from the skill hierarchy Excel |
| Assessment / frustration ingest APIs | Same learner IDs across the system |

**You do not:**
- generate quiz questions (Component 2),
- own engagement sensing (Component 3),
- own lesson content generation (Component 1).

**Shared key across everyone:** `topic_id` from `Data/Skill-Heirarchies-G6-G9.xlsx`  
Format: `G{grade}_S{section}_{DOMAIN}_{CONCEPT}` — e.g. `G6_S8_ELE_CONDINS` (`S` = curriculum **section**).

---

## 2. Big picture — how the pieces connect

```text
                    ┌─────────────────────────────────────┐
  Question Engine   │  POST /api/v1/assessment-submit     │
  (correct/wrong) ──►│  → BKT predict_update (0/1)         │
                    │  → store attempt + distractors      │
                    └──────────────┬──────────────────────┘
                                   │
  Engagement        ┌──────────────▼──────────────────────┐
  (frustration) ────►│  POST /api/v1/engagement/...        │
                    │  → tone/persona only (NOT mastery)  │
                    └──────────────┬──────────────────────┘
                                   │
  Student chat      ┌──────────────▼──────────────────────┐
  (Streamlit 8501) ─►│  /tutor/hint-auto-topic             │
                    │  topic route → RAG → persona → LLM  │
                    │  optional dialogue BKT (policy)     │
                    └──────────────┬──────────────────────┘
                                   │
  Teacher           ┌──────────────▼──────────────────────┐
  (Streamlit 8502) ─►│  mastery matrix + at-risk alerts     │
                    │  student profile / Misconception Cloud│
                    └─────────────────────────────────────┘
```

**Demo line:** *“One shared BKT brain. Quizzes send ground-truth. The tutor adapts to mastery. The dashboard shows who needs help.”*

---

## 3. Socratic chatbot — working flow

### What it is

A **state-aware Socratic hint generator** — not a answer-dumping chatbot.

- Grounded in the **Grades 6–9 science syllabus** (RAG / Chroma).
- Depth of help depends on **current BKT mastery**.
- Voice depends on **persona** (+ optional frustration tone).
- Ends with **one** guiding question; never gives the full answer.

### Endpoints

| Endpoint | When to use |
|----------|-------------|
| `POST /tutor/hint-auto-topic` | Student UI (default) — topic inferred each turn |
| `POST /tutor/hint` | Integrations that already know `topic_id` |

### One turn, step by step

```text
Student message
       │
       ▼
1. Acknowledgment? ("thanks", "I get it")
   → short closure; skip RAG / LLM Socratic loop / BKT
       │
       ▼
2. Topic routing (auto-topic only)
   → infer topic_id from keywords vs 57 curriculum topics
   → if topic changed mid-chat, drop old history for this turn
       │
       ▼
3. Read current mastery P(L) for (user_id, topic_id)
   → pick hint mode:
        scaffold  if P(L) < 0.5
        balanced  if 0.5 ≤ P(L) ≤ 0.8
        nudge     if P(L) > 0.8
       │
       ▼
4. Frustration resolve (optional)
   → external cue from Component 3 (decayed) + chat heuristics
   → affects tone / may nudge persona to Practical Encourager
   → NEVER updates BKT
       │
       ▼
5. Persona resolve
   → client pin / env default / high-frustration nudge / random
   → practical_encourager | analytical_coach | curious_explorer
       │
       ▼
6. RAG retrieve syllabus chunks for that topic
       │
       ▼
7. Build prompt (guardrails + 9-state persona×mode + few-shots)
       │
       ▼
8. Groq LLM → JSON { hint_text, interaction_score }
       │
       ▼
9. Optional BKT update (see TUTOR_BKT_POLICY below)
       │
       ▼
10. Log turn + return hint, topic, persona, mode, mastery fields
```

### Hint modes (say this in the demo)

| Mode | Mastery | Tutor behaviour |
|------|---------|-----------------|
| **Scaffold** | Low (&lt; 0.5) | More guidance, everyday metaphors / micro-steps |
| **Balanced** | Mid | Short contrast / discrimination question |
| **Nudge** | High (&gt; 0.8) | Transfer / “what if” — minimal re-teaching |

### Personas (3 × 3 = 9-state matrix)

| Persona | Feel |
|---------|------|
| Practical Encourager | Warm, real-world metaphors |
| Analytical Coach | Precise, cause → mechanism → outcome |
| Curious Explorer | Wonder-driven, hypotheses |

All personas share hard rules: textbook grounding only, no full answers, one question at the end, short JSON output.

### Chat vs quiz — who updates mastery?

Controlled by env **`TUTOR_BKT_POLICY`** (default **`strict`**):

| Policy | Chat updates BKT? |
|--------|-------------------|
| **`strict`** | Only decisive scores: ≥ 0.78 → correct (1); ≤ 0.42 → incorrect (0); mid-range skipped |
| **`quiz_only`** | Never — only assessment-submit updates mastery |
| **`legacy`** | Older lenient mapping (can inflate mastery) |

**Demo tip:** For a clean “quiz drives mastery” story, say you can run `quiz_only`. By default, clear chat understanding/confusion can also nudge mastery carefully.

### Frustration (Epic 7) — one sentence

Frustration changes **how** the tutor speaks (and may prefer Encourager when high). It does **not** change P(L).

---

## 4. BKT mastery — how it is calculated

### What the score means

**Mastery = P(L)** = probability the learner has **learned** that skill/topic.

- Range: **0.0 – 1.0** (show as % on the dashboard).
- Keyed by **`(user_id, topic_id)`**.
- **Not** “score on one quiz” — it’s a latent belief updated after each accepted observation.

### Where parameters come from

Fitted per topic from `synthetic_logs.csv` via **pyBKT** (`ScienceBKT` in `bkt_engine.py`):

| Parameter | Intuition |
|-----------|-----------|
| **prior** | Starting P(L) for a new learner on that topic |
| **learn** | Chance they learn from this practice opportunity |
| **guess** | Chance of correct without having learned |
| **slip** | Chance of wrong even though they know it |
| **forget** | Small decay between observations |

### What happens on one observation (correct = 1 / incorrect = 0)

1. **Bayesian update** using guess/slip (a wrong answer doesn’t always mean “not learned”).
2. **Learn + forget** transition on that posterior.
3. **Smoothing** so live mastery doesn’t spike after a few lucky corrects:
   - damping (default 0.60),
   - early-attempt cap (default max ~0.90 for first few attempts).
4. Store new P(L) for that `(user_id, topic_id)`.

### What can feed an observation?

| Source | Label | Reliability |
|--------|-------|-------------|
| **`POST /api/v1/assessment-submit`** | `is_correct` → 0/1 | Ground truth (primary for demos with Question Engine) |
| Tutor dialogue | From `interaction_score` if policy allows | Soft / policy-gated |

**One shared engine** (`get_shared_bkt_engine()`) — quiz and tutor update the **same** trajectory.

### Per-attempt BKT “at_risk” flag (assessment response)

Separate from the **dashboard** multi-signal alert. After `predict_update`, `risk_flag` can be true if:

- mastery **dropped** after this attempt, or  
- **3 incorrect in a row** on that topic.

Question Engine can use `updated_mastery_probability` + `risk_flag` for adaptive difficulty.

### Demo lines for BKT

- *“We don’t store a static percentage — we update a Bayesian belief after each trusted outcome.”*
- *“Guess and slip mean one wrong answer doesn’t zero you out; one lucky guess doesn’t max you out.”*
- *“Assessment submit is the trusted path; chat only updates when the policy says the score is decisive.”*

---

## 5. Teacher dashboard analytics

**UI:** `Streamlit-UIs/teacher_dashboard.py` → http://localhost:8502  
**Backend:** FastAPI analytics endpoints in `main.py`

### Modes (important for demos)

| Mode | Meaning |
|------|---------|
| **`replay_logs`** | Replay `synthetic_logs.csv` through BKT → stable classroom baseline |
| **`live_state`** | Current runtime state from assessment/tutor events (good after live quiz submits) |

Use the **same mode** for heatmap and at-risk so numbers stay consistent.

### Classroom mastery heatmap

- **Rows:** students  
- **Columns:** topics (up to 57 from the Excel hierarchy)  
- **Cell:** current P(L)

| Color | Mastery |
|-------|---------|
| Red | &lt; 0.50 |
| Orange | 0.50 – 0.79 |
| Green | ≥ 0.80 |

API: `POST /api/v1/mastery/matrix`

### At-risk students — how the alert is calculated

API: `POST /api/v1/analytics/at-risk-students`

For each student, pick a **current topic** (latest activity / most attempts / fallback).

Then evaluate **three signals**:

| # | Signal | Rule |
|---|--------|------|
| 1 | **Low Mastery** | P(L) **&lt; 0.45** |
| 2 | **Negative Velocity** | Last **3** performance signals are **strictly decreasing** (`a > b > c`) |
| 3 | **Weak Recent Performance** | Average of recent signals **&lt; 0.40** (window ~5) |

**Flagged if at least 2 of 3 are true.**

**Critical override:** if P(L) **&lt; 0.20** and recent performance is weak → escalate as **Critical Low Mastery** (risk score at least 85).

**Risk score on the card (capped at 100):**

| Signal | Points |
|--------|--------|
| Low Mastery | +40 |
| Negative Velocity | +30 |
| Weak Recent Performance | +30 |

**Where “signals” come from in live mode:** quiz 0/1 outcomes and tutor interaction scores over time — so declining quiz/chat performance shows as negative velocity.

**Demo line:** *“At-risk is not just low mastery — we also look for a declining trend and weak recent work. Two of three triggers an alert.”*

### Student deep-dive (Misconception Cloud)

API: `GET /api/v1/analytics/student-profile/{user_id}`

- Mastery timeline, BKT params, chat history, frustration samples.
- **Misconception Cloud:** counts of wrong-MCQ **`distractor_label`**s from Question Engine.
  - Live labels when assessments include distractors → `distractor_source: question_engine_live`
  - Otherwise simulated tags from synthetic log replay as fallback.

---

## 6. What to run for a live demo

```powershell
# Terminal 1 — API
.\.venv\Scripts\Activate.ps1
cd FastAPI-Backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — Tutor
.\.venv\Scripts\Activate.ps1
streamlit run Streamlit-UIs/tutor-chatbot.py --server.port 8501

# Terminal 3 — Dashboard
.\.venv\Scripts\Activate.ps1
streamlit run Streamlit-UIs/teacher_dashboard.py --server.port 8502
```

| App | URL |
|-----|-----|
| Tutor | http://localhost:8501 |
| Dashboard | http://localhost:8502 |
| API docs | http://127.0.0.1:8000/docs |

### Suggested 2-minute narrative

1. **Hub role** — BKT + tutor + dashboard; other components plug in via APIs.  
2. **Chat** — student asks about conductors; system infers `G6_S8_ELE_CONDINS`, picks scaffold/balanced/nudge from mastery, returns a Socratic hint.  
3. **Quiz** — `assessment-submit` wrong/correct → mastery moves; optional distractor label feeds Misconception Cloud.  
4. **Dashboard** — heatmap colors; at-risk cards from 2-of-3 rule; deep-dive shows misconceptions.

---

## 7. Key files (if someone asks “where is this coded?”)

| Concern | File |
|---------|------|
| API hub | `FastAPI-Backend/main.py` |
| Socratic tutor + personas + frustration | `FastAPI-Backend/socratic_tutor.py` |
| BKT math | `FastAPI-Backend/bkt_engine.py` |
| RAG / syllabus | `FastAPI-Backend/knowledge_base.py` |
| Tutor UI | `Streamlit-UIs/tutor-chatbot.py` |
| Teacher UI | `Streamlit-UIs/teacher_dashboard.py` |
| Topic IDs | `Data/Skill-Heirarchies-G6-G9.xlsx` |
| Baseline learner logs | `Data/synthetic_logs.csv` |

---

## 8. One-sentence summaries (memorize these)

| Topic | One sentence |
|-------|----------------|
| **Component** | We track mastery with BKT, tutor with a syllabus-grounded Socratic chatbot, and surface classroom risk on a teacher dashboard. |
| **Chatbot** | Each turn: route topic → read mastery → retrieve textbook → persona + mode prompt → LLM hint → optional careful BKT update. |
| **BKT** | P(L) is updated Bayesian-style after each 0/1 observation, using guess/slip/learn/forget, then smoothed for live use. |
| **At-risk** | Alert if ≥2 of: low mastery (&lt;0.45), declining last-3 signals, weak recent average (&lt;0.40), with a critical override below 0.20. |
