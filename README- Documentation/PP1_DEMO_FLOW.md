# PP1 — 4-minute component demo flow

Use this when presenting **your individual component** (FastAPI Socratic tutor + BKT + teacher analytics). Base URL: `http://127.0.0.1:8000` unless you change it.

---

## Before you go live (30 seconds to verify)

1. Activate project venv and start the API:

   ```bash
   uvicorn main:app --reload
   ```

2. Set `GROQ_API_KEY` (e.g. in `.env`) so tutor endpoints return real hints.

3. Optional UIs (pick one for the “student” part of the demo):

   - `streamlit run tutor-chatbot.py` — chat UI
   - `streamlit run teacher_dashboard.py` — heatmap + analytics

4. **Demo constants** (stay consistent for 4 minutes):

   - `user_id`: e.g. `user_003`
   - `topic_id`: e.g. `G6_S1_ORG_CHARS` (living vs non-living)

Valid topic IDs for this build are the seven `G6_...` skills listed in `DEMO_FLOW.md`.

---

## 4-minute speaking + demo script (timed)

| Time | What you do | What you say (talk track) |
|------|-------------|---------------------------|
| **0:00–0:45** | Open Swagger UI at `http://127.0.0.1:8000/docs` or show your slide: sub-problem + solution | “My sub-problem is personalized science support and teacher visibility. I deliver a **Socratic tutor API** plus a **shared BKT mastery model** and **analytics APIs** so one learner has one mastery trajectory per topic, and teachers see class-level risk and mastery.” |
| **0:45–1:45** | `GET /health` → `POST /api/v1/assessment-submit` (one wrong + one correct) | “Quiz integration is **`/api/v1/assessment-submit`**: ground-truth correct or wrong updates the same BKT state the tutor reads. Watch `updated_mastery_probability` move on trusted labels.” |
| **1:45–2:45** | `POST /api/v1/engagement/frustration-cue` (high score, e.g. 0.82) → `POST /tutor/hint` or `/tutor/hint-auto-topic` with a weak student message | “Frustration is separate: **`/api/v1/engagement/frustration-cue`** only steers **tone** on the next tutor turn; it does not change BKT. Then I call the tutor—hint style follows mastery band and the frustration guidance.” Point to JSON: `hint_text`, `mastery_probability_before`, `bkt_updated`, `frustration_level_used`. |
| **2:45–3:45** | Teacher view: Streamlit dashboard **live_state** OR show `POST /api/v1/mastery/matrix` and `POST /api/v1/analytics/at-risk-students` in Swagger/docs | “For teachers I expose **`/api/v1/mastery/matrix`**, **`/api/v1/analytics/at-risk-students`**, and **`/api/v1/analytics/student-profile/{user_id}`**. The dashboard consumes these; live mode shows this running session, replay mode can show a stable classroom picture from logs.” |
| **3:45–4:00** | Optional: one line + `evaluation_outputs/summary.json` or “run `evaluation.py`” | “For validation I report **AUC and RMSE** from held-out learners—details are at the bottom of this doc.” |

**If you only have curl/HTTP file:** use the JSON examples in `DEMO_FLOW.md` for the same steps in order: health → assessment → frustration → tutor → matrix / at-risk.

---

## Minimal request sequence (copy-paste order)

1. **Health** — `GET /health` → `{"status":"ok"}`

2. **Assessment (integration)** — `POST /api/v1/assessment-submit`

   ```json
   { "user_id": "user_003", "topic_id": "G6_S1_ORG_CHARS", "is_correct": false }
   ```

3. **Engagement (integration)** — `POST /api/v1/engagement/frustration-cue`

   ```json
   {
     "user_id": "user_003",
     "topic_id": "G6_S1_ORG_CHARS",
     "frustration_score": 0.82,
     "source": "pp1_demo"
   }
   ```

4. **Tutor (core)** — `POST /tutor/hint-auto-topic`

   ```json
   {
     "user_id": "user_003",
     "student_answer": "Is a rock alive because it sits there forever?",
     "topic_id": "G6_S1_ORG_CHARS",
     "context_k": 4
   }
   ```

5. **Teacher analytics** — e.g. `POST /api/v1/mastery/matrix` with `mode: "live_state"` and your demo `user_id` + `topic_id` list; then `POST /api/v1/analytics/at-risk-students` with `mode: "live_state"`.

---

## Demo tips

- **One storyline:** same `user_id` and `topic_id` end-to-end so mastery and frustration line up.
- **Strict policy (default):** dialogue updates BKT only when the model’s `interaction_score` is decisive (≥ 0.78 → treat as correct evidence, ≤ 0.42 → incorrect); mid scores skip BKT. Say: “Quiz is authoritative; chat is gated.”
- **If LLM fails:** fall back to assessment-only narrative and `replay_logs` on the dashboard.

---

## Technical Q&A (for viva / report)

### How did I calculate AUC?

**AUC** (Area Under the ROC Curve) measures how well **predicted probability of correctness** ranks **actual** correct/incorrect outcomes (0/1).

- **In-sample / per-skill training (`ScienceBKT.train_model()` in `bkt_engine.py`):** For each topic, the engine fits (or calibrates) a model, builds a sequence of predictions, then sets `y_true` to the observed `correct` column and `y_pred` to the model’s predicted correctness probability (`correct_predictions` from pyBKT, or the internal sequential predictor when pyBKT is unstable). It then calls **`sklearn.metrics.roc_auc_score(y_true, y_pred)`**. If every label is the same class, AUC is not defined and is reported as N/A.

- **Holdout evaluation (`evaluation.py`):** Users are split per topic into train vs test sets. Parameters are fit on **train users only**; then the same one-step-ahead probability sequence is applied to **test users’** attempts. AUC is again **`roc_auc_score`** on those test rows’ true labels vs predicted probabilities.

RMSE uses **`sqrt(mean_squared_error(y_true, y_pred))`** on the same pairs.

---

### How is the interaction score calculated?

The **`interaction_score` is not computed by a fixed formula in code**. It is **produced by the LLM** as part of a strict JSON response (`hint_text` + `interaction_score`). The system prompt in `socratic_tutor.py` tells the model to output a number from **0.0 to 1.0** reflecting how well the student’s **latest** message aligns with **correct science** in the retrieved textbook chunks, with calibration bands (e.g. wrong/confused usually ≤ 0.35, clearly correct ≥ 0.78).

After generation, the server **parses** the JSON and **clamps** the score to `[0, 1]`. If the score is missing or invalid, **no BKT update** runs that turn.

**Optional link to BKT (policy-dependent):**

- **`strict` (default):** `interaction_score ≥ 0.78` → BKT label `1`; `≤ 0.42` → label `0`; between → **no** `predict_update`.
- **`quiz_only`:** dialogue **never** updates BKT; only `/api/v1/assessment-submit` does.
- **`legacy`:** a discounted mapping (`score * 0.5` then threshold 0.25) maps to 0/1.

The API may expose **`interaction_score_effective`** in the response for transparency after policy handling.

---

### How does the BKT mastery logic work?

**Mastery** is **P(L)** — estimated probability the learner **has learned** the skill (your `topic_id` / `skill_name`).

1. **Parameters** (prior, learn, guess, slip, forget) are obtained per skill from **`synthetic_logs.csv`** via pyBKT fitting, with a **fallback calibrator** when the fit is degenerate (`bkt_engine.py`).

2. **State** is stored per **`(user_id, skill_name)`**: current mastery, attempt count, consecutive incorrect streak (for risk heuristics).

3. **On each observation** (`predict_update` with `is_correct` in `{0,1}`):

   - **Bayesian update** using **slip** and **guess** (wrong answers are not always “not learned”; right answers are not always “learned”).
   - Then **learning** and **forgetting** transition on the latent state.

4. **Live smoothing** (same file): the raw BKT step is blended toward the previous mastery using a **damping** factor and **per-step caps** so mastery does not jump unrealistically on few chat or quiz events (see env vars like `BKT_UPDATE_DAMPING` in `bkt_engine.py`).

5. **Two input channels, one engine:** **`/api/v1/assessment-submit`** always passes trusted 0/1. The **tutor** may call `predict_update` only when policy and a valid `interaction_score` allow a decisive dialogue label.

For narrative detail aligned with the code paths, see `BKT MASTERY EXPLAINED.md` and `SOCRATIC_CHATBOT.md`.
