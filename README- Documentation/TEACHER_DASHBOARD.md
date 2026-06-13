# Teacher Dashboard

This document explains how values in `teacher_dashboard.py` are generated for:

- **⚠️ Priority Alerts: Students At-Risk**
- **Classroom Mastery Heatmap**

## What the dashboard shows

The heatmap is a matrix:

- **Rows (Y-axis):** student IDs
- **Columns (X-axis):** science topic IDs (`skill_name` values used by BKT)
- **Cell value:** current BKT mastery probability `P(L)` in `[0, 1]`

Color bands in the heatmap:

- **Red:** `< 0.50`
- **Orange:** `0.50 - 0.79`
- **Green:** `>= 0.80`

---

## Data flow

1. `teacher_dashboard.py` sends POST requests to:
   - `POST /api/v1/analytics/at-risk-students`
   - `POST /api/v1/mastery/matrix`
2. Both calls now use the same selected `mode` (`live_state` or `replay_logs`) so
   alerts and heatmap are consistent.
3. FastAPI (`main.py`) computes:
   - at-risk alert cards (student-level risk analysis)
   - mastery matrix values for heatmap cells
4. Streamlit renders:
   - red priority alert cards at the top
   - Plotly mastery heatmap below

---

## Predictive at-risk alert logic

The endpoint `POST /api/v1/analytics/at-risk-students` supports:

- `mode = "live_state"`: uses current in-memory events and mastery state.
- `mode = "replay_logs"`: replays historical `synthetic_logs.csv` interactions.

For each student, it evaluates a **current topic** (latest event topic, else topic with most attempts, else first selected topic).

### Criteria

At-risk evaluation is now a **2-of-3 signal rule** on the current topic:

1. **Low Mastery**
   - `P(L) < 0.45`
2. **Negative Velocity**
   - Last 3 signals are strictly decreasing (`a > b > c`)
   - In `live_state`, signals come from:
     - quiz outcomes (`assessment-submit`: 0 or 1)
     - tutor interaction scores (`interaction_score_effective`: 0..1)
   - In `replay_logs`, velocity uses the last 3 replayed mastery points on the topic.
3. **Weak Recent Performance**
   - Recent performance average `< 0.40` (rolling window logic differs slightly by mode)

Students are flagged when **at least 2 of the 3** signals are true.
There is also a severe-case override:

- If `P(L) < 0.20` and recent performance is weak, risk is escalated as **Critical Low Mastery**.

### Risk score shown on each alert card

Risk score is a weighted sum (capped to 100):

- Low Mastery: `+40`
- Negative Velocity: `+30`
- Weak Recent Performance: `+30`

Critical override:

- If mastery is below critical threshold and recent performance is weak, minimum risk score becomes `85`.

Only students meeting at least one criterion are returned. Cards show:

- Student ID
- Topic
- Reason string (which criteria triggered)
- Risk Score (%)
- diagnostics (`P(L)`, recent signal tail, recent performance average, triggered signal count)

---

## How mastery values are generated

The API supports two modes:

## 1) `replay_logs` (recommended for baseline dashboard)

This mode generates **real values from your dataset**, not random/fake values.

Processing steps in `main.py`:

1. Create a fresh `ScienceBKT(data_path="synthetic_logs.csv")`.
2. Call `initialize_skills()` to load valid topic IDs.
3. Filter `synthetic_logs.csv` by requested `student_ids` and `topic_ids`.
4. Replay each filtered row in time order using:
   - `predict_update(user_id, skill_name, is_correct, response_time)`
5. After replay, fetch final mastery for each requested student-topic pair using:
   - `get_current_mastery_probability(user_id, topic_id)`

So each heatmap cell is the **BKT-estimated mastery after replaying actual logged interactions** for that student/topic.

## 2) `live_state` (runtime state)

This mode reads mastery from the shared in-memory engine currently running in your API process.

Those values come from live events such as:

- `POST /api/v1/assessment-submit` (ground-truth quiz correctness)
- Tutor updates from `/tutor/hint*` **when valid `interaction_score` is present and tutor policy permits BKT update**

Live state is now rehydrated from persisted event logs on startup.

---

## Why `synthetic_logs.csv` can still produce mastery values

`synthetic_logs.csv` does **not** store mastery directly.  
It stores interaction outcomes (correct/incorrect, etc.).

Mastery is computed by running those outcomes through BKT transition logic (`predict_update`) step by step.

---

## Unknown topic IDs behavior

If the dashboard requests a topic not present in BKT `skill_map`:

- API returns that cell as `null` (instead of crashing)
- response includes `unknown_topic_ids`
- dashboard shows those cells as blank and warns the user

This ensures robustness when topic IDs are mistyped or not in the training logs.

---

## Important implementation files

- `teacher_dashboard.py`  
  Streamlit UI + heatmap rendering.

- `main.py`  
  `POST /api/v1/analytics/at-risk-students` and `POST /api/v1/mastery/matrix`.

- `bkt_engine.py`  
  Core BKT update functions (`predict_update`, `get_current_mastery_probability`).
