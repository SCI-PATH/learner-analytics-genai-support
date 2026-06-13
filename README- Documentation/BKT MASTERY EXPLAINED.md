# BKT mastery explained

This document describes **what the mastery score means** in this project and **how it changes** as a learner uses the tutor or completes assessments. The behavior matches the implementation in `bkt_engine.py` (Bayesian Knowledge Tracing) and `socratic_tutor.py` / `main.py` (how observations reach the engine).

---

## What is the mastery score?

The mastery value is **P(L)** — the engine’s estimate of the probability that the learner **has learned** the target skill (your curriculum `topic_id` / `skill_name`, e.g. a Grade-6 topic id such as `G6_...`).

- It is a **number between 0 and 1** (often shown as a percentage).
- It is **not** a quiz percentage from a single test; it is a **latent** belief that gets revised after each **binary** observation the system accepts for that learner and skill.

Internally, the engine keeps one row of state per **(user_id, skill_name)** in `student_state`: current `mastery`, attempt count, and consecutive incorrect streak (used for risk rules).

---

## Where do the numbers come from? (Parameters)

Before live updates, each skill gets **BKT parameters** fitted from your log data (`synthetic_logs.csv`) using **pyBKT** (`ScienceBKT` in `bkt_engine.py`). For each skill, the engine stores (among others):

| Parameter | Role (intuition) |
|-----------|------------------|
| **prior** | Starting P(L) before any live observation for a new learner–skill pair (unless state already exists). |
| **learn** | How much P(L) can increase after an observation because the learner may have *just* learned. |
| **guess** | Chance a not-yet-learned learner still answers correctly. |
| **slip** | Chance a learned learner still answers incorrectly. |
| **forget** | Small decay so mastery can drift down between observations. |

If the automated fit is unreliable for a skill, the code can **fall back to calibrated defaults** so updates remain stable.

---

## How is mastery updated after one observation?

Each accepted observation is **correct (1)** or **incorrect (0)**. Given the **previous** mastery \(P_{\text{prev}}\) and parameters, the code does two conceptual steps (see `_apply_bkt_observation` in `bkt_engine.py`):

### 1. Bayesian update from the outcome (slip and guess)

The engine asks: *Given this correct/incorrect response, how should we revise P(L)?*  
Wrong answers are not treated as “always means not learned,” and right answers are not treated as “always learned,” because of **slip** and **guess**.

- **If the response is correct:** the posterior numerator favors the learner having learned (weight \(1 - \text{slip}\)) versus guessing (weight \(\text{guess}\) when not learned).
- **If the response is incorrect:** the update uses **slip** (learned but wrong) versus **\(1 - \text{guess}\)** (not learned and wrong).

That yields a **posterior** P(L) after seeing this one outcome.

### 2. Learning and forgetting transition

After that posterior, the model applies:

- **Learning:** probability mass moves from “not learned” toward “learned” using the **learn** rate:  
  `next = posterior + (1 - posterior) * learn`
- **Forgetting:** a small multiplicative decay:  
  `next *= (1 - forget)`

Finally, the value is **clipped** to \([0, 1]\). In the current implementation, this raw BKT output is then passed through a conservative live-update smoother:

- `smoothed = previous + damping * (raw - previous)`
- default `damping` is controlled by env **`BKT_UPDATE_DAMPING`** (default `0.60`)
- on very early attempts, mastery is also capped by **`BKT_EARLY_MASTERY_CAP`** (default `0.90` for first `BKT_EARLY_MASTERY_ATTEMPTS=5`)

This is why mastery no longer jumps too aggressively after only a few consecutive correct answers.

The **smoothed** value is stored as the new mastery for that `(user_id, skill)`.

### Risk flags (separate from the formula)

`predict_update` also updates **consecutive incorrect** streaks and may set **at_risk** if mastery drops after the attempt or if there are **three incorrects in a row** on that skill. That does not change the Bayes formula; it is an extra signal for the API/UI.

---

## How does the score move as the conversation progresses?

There is **one shared** `ScienceBKT` instance and **one mastery trajectory per learner per skill**. Two kinds of events can append observations to that same trajectory.

### A. Tutor dialogue (policy-controlled mastery updates)

When the learner uses a **Socratic hint** endpoint (`socratic_tutor.py`):

1. The tutor reads **current mastery** (without adding an observation) to choose hint style.
2. The LLM returns JSON including **`interaction_score`** (0–1), meant to reflect how well the student’s message aligns with the topic.
3. Whether dialogue updates mastery depends on env **`TUTOR_BKT_POLICY`**:
   - **`strict` (default):** update only on decisive scores (`interaction_score >= 0.78` -> label `1`, `<= 0.42` -> label `0`); ambiguous mid-range scores skip BKT updates.
   - **`quiz_only`:** dialogue never calls `predict_update`; only quiz events update mastery.
   - **`legacy`:** older lenient mapping (`score * 0.5 >= 0.25` => label `1`), kept for backward compatibility.
4. So tutor chat can be either update-enabled or update-disabled depending on this policy.

### B. Assessment / quiz (ground truth)

When the application submits a verified outcome via **`POST /api/v1/assessment-submit`** (`main.py`), it calls the **same** engine with **`is_correct` true → 1, false → 0** (no LLM discount). That is the intended path for **reliable** labels.

### Order of events

Mastery is always sequential on the same `(user_id, skill)` state. Earlier observations affect later ones because each step starts from the **updated** P(L). In `quiz_only`, those observations come only from assessments; in `strict`/`legacy`, decisive chat turns may also contribute.

---

## Summary

| Question | Answer |
|----------|--------|
| What does mastery represent? | Estimated P(learned) for that skill, in \([0,1]\). |
| What changes it? | Each call to `predict_update` with a binary 0/1 observation. |
| First time seeing a learner on a skill? | Starts from the fitted **prior** for that skill. |
| Does every chat message update mastery? | **No** — only if `interaction_score` is valid and policy allows update (`strict` decisive band / `legacy`). In `quiz_only`, chat never updates mastery. |
| One engine for tutor and quiz? | **Yes** — shared `ScienceBKT` / `get_shared_bkt_engine()` so there is a single mastery path per learner per skill. |

### Practical interpretation for demos

- There is **no fixed interval jump** (e.g., +10% each time).  
- Jump size depends on current mastery + skill parameters (`learn`, `guess`, `slip`, `forget`).
- After this update, the engine also applies damping/cap controls to reduce unrealistic spikes from short streaks.

For the exact formulas and edge cases, see **`ScienceBKT._apply_bkt_observation`** and **`ScienceBKT.predict_update`** in `bkt_engine.py`, and the tutor branch that sets **`bkt_updated`** in `socratic_tutor.py`.
