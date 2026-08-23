# Frustration Score Calculation

SCI_PATH turns **17 behavioral metrics** into a single **frustration score (0–100)** and a **frustration level**. That profile is what the storyline generator sends to Grok.

Implementation in the repo: `frontend/src/storyline/frustration/FrustrationEngine.js`.

```
Student Performance
        ↓
17 Behavioral Metrics
        ↓
Normalization (0–100)
        ↓
Weighted Frustration Calculation
        ↓
Frustration Score (0–100)
        ↓
Frustration Level
        ↓
Grok Storyline Generation
```

---

## 1. Collect the 17 behavioral metrics

| Metric | Weight | Code key |
| --- | ---: | --- |
| Incorrect answer rate | 10% | `incorrectAnswerRate` |
| Consecutive wrong answers | 8% | `consecutiveWrongAnswers` |
| Answer time deviation | 8% | `answerTimeDeviation` |
| Increasing answer time | 6% | `increasingAnswerTime` |
| Retry count | 6% | `retryCount` |
| Failed attempts | 6% | `failedAttempts` |
| Hint usage | 6% | `hintUsage` |
| Answer changes | 4% | `answerChanges` |
| Rapid clicking | 5% | `rapidClicking` |
| Excessive mouse movement | 4% | `excessiveMouseMovement` |
| Mouse inactivity | 5% | `mouseInactivity` |
| Repeated UI interaction | 4% | `repeatedUIInteraction` |
| Questions skipped | 5% | `questionsSkipped` |
| Activity restarts | 4% | `activityRestarts` |
| Level restarts | 4% | `levelRestarts` |
| Enemy deaths | 5% | `enemyDeaths` |
| Performance decline | 6% | `performanceDecline` |
| **Total** | **100%** | |

The listed weights sum to **96%**. The engine rescales each weight by `weight / 0.96` so the mix stays the same and the final score still lands on 0–100.

---

## 2. Normalize every metric to 0–100

Metrics use different units, so **do not add raw values**. For each metric:

```
Normalized Metric = (Observed Value / Maximum Expected Value) × 100
```

Then clamp:

- if value > 100 → 100
- if value < 0 → 0

**Incorrect answer rate** is already a percentage. A 40% error rate normalizes to **40**.

**Retry count** example:

- Retry count = 8
- Maximum expected retries = 10

```
Normalized retry score = (8 / 10) × 100 = 80
```

Default caps used by the engine:

| Metric | Cap (`NORMALIZATION_CAPS`) |
| --- | ---: |
| Consecutive wrong answers | 5 |
| Answer time over baseline | 1.0 (100% slower → 100) |
| Answer time trend | 0.5 (+50% trend → 100) |
| Retry count | 10 |
| Failed attempts | 10 |
| Hint usage | 10 |
| Answer changes | 12 |
| Rapid click count | 20 |
| Mouse inactivity (seconds) | 60 |
| Repeated UI interactions | 10 |
| Activity restarts | 5 |
| Level restarts | 5 |
| Enemy deaths | 8 |

`incorrectAnswerRate`, `questionsSkipped`, `excessiveMouseMovement`, and `performanceDecline` are already on (or mapped onto) a 0–100 scale.

---

## 3. Calculate the weighted score

For each metric:

```
Metric Contribution = Normalized Metric × Weight
```

Example: incorrect-answer score **60**, weight **10%**:

```
Contribution = 60 × 0.10 = 6
```

Do this for all 17 metrics, then:

```
Frustration Score =
  Contribution₁ + Contribution₂ + … + Contribution₁₇
```

Clamp the result:

```
FS = clamp(FS, 0, 100)
```

The final score is between **0** and **100**.

---

## 4. Example

Suppose a student produces these normalized scores:

| Metric | Normalized score | Weight | Contribution |
| --- | ---: | ---: | ---: |
| Incorrect answers | 70 | 10% | 7.00 |
| Consecutive wrong | 60 | 8% | 4.80 |
| Answer-time deviation | 80 | 8% | 6.40 |
| Increasing answer time | 70 | 6% | 4.20 |
| Retry count | 80 | 6% | 4.80 |
| Failed attempts | 60 | 6% | 3.60 |
| Hint usage | 70 | 6% | 4.20 |
| Answer changes | 50 | 4% | 2.00 |
| Rapid clicking | 40 | 5% | 2.00 |
| Mouse movement | 30 | 4% | 1.20 |
| Mouse inactivity | 60 | 5% | 3.00 |
| Repeated UI interaction | 50 | 4% | 2.00 |
| Questions skipped | 30 | 5% | 1.50 |
| Activity restarts | 40 | 4% | 1.60 |
| Level restarts | 20 | 4% | 0.80 |
| Enemy deaths | 50 | 5% | 2.50 |
| Performance decline | 70 | 6% | 4.20 |
| **Total** | | | **55.80** |

```
Frustration Score = 55.80  →  MODERATE
```

---

## 5. Frustration categories

| Score | Level |
| ---: | --- |
| 0 – 20 | `VERY_LOW` |
| 21 – 40 | `LOW` |
| 41 – 60 | `MODERATE` |
| 61 – 80 | `HIGH` |
| 81 – 100 | `VERY_HIGH` |

Example payload passed downstream:

```json
{
  "frustrationScore": 55.8,
  "frustrationLevel": "MODERATE"
}
```

---

## 6. Use the student's baseline for answer time

A longer answer is **not** automatically frustration. Compare against that student's normal pace.

- Baseline average answer time = 15 seconds
- Current average answer time = 24 seconds

```
Deviation = ((24 - 15) / 15) × 100 = 60%
```

The answer-time frustration indicator is about **60 / 100**.

Do **not** treat “24 seconds” as high frustration on its own. Some students naturally answer more slowly.

---

## 7. Performance decline

Compare **current** accuracy to **previous** accuracy.

- Previous accuracy = 85%
- Current accuracy = 60%

```
((85 - 60) / 85) × 100 = 29.4%
```

Performance decline score = **29.4**.

A student who usually does well and then drops suddenly is a stronger frustration signal than someone whose accuracy was already around 60%.

---

## 8. Consecutive wrong answers

Treat streaks separately from overall incorrect-answer rate.

```
Wrong → Wrong → Wrong → Wrong
```

is a stronger signal than:

```
Correct → Wrong → Correct → Wrong
```

even if both students end with the same accuracy.

Normalize against a maximum threshold (engine cap = **5**):

- Student = 4 consecutive wrong

```
Score = (4 / 5) × 100 = 80
```

---

## 9. Final formula

Every variable below is already normalized to 0–100:

```
FS =
  (IA  × 0.10) +   // incorrect answer rate
  (CW  × 0.08) +   // consecutive wrong answers
  (AT  × 0.08) +   // answer time deviation
  (IAT × 0.06) +   // increasing answer time
  (RC  × 0.06) +   // retry count
  (FA  × 0.06) +   // failed attempts
  (HU  × 0.06) +   // hint usage
  (AC  × 0.04) +   // answer changes
  (RCk × 0.05) +   // rapid clicking
  (EM  × 0.04) +   // excessive mouse movement
  (MI  × 0.05) +   // mouse inactivity
  (RUI × 0.04) +   // repeated UI interaction
  (QS  × 0.05) +   // questions skipped
  (AR  × 0.04) +   // activity restarts
  (LR  × 0.04) +   // level restarts
  (ED  × 0.05) +   // enemy deaths
  (PD  × 0.06)     // performance decline

FS = clamp(FS, 0, 100)
```

Pass `frustrationScore` and `frustrationLevel` into the existing storyline generator. Do not mention frustration, ranks, or struggling in the student-facing narrative — the generator uses the score only to choose complexity and tone.
