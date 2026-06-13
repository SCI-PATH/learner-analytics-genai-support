# Integrations: Assessment + Engagement -> Tutor Hub

This document explains the two external API integrations your module exposes, and why **you** implement these endpoints even though your teammates produce the data.

## Why these endpoints are in your component

Your module is the **central intelligence hub** (BKT + tutor logic).  
That means other components send events **to you**, and you define the receiver contracts.

- Question Engine (Component 2) is the **producer** of quiz outcomes.
- Engagement Module (Component 3) is the **producer** of frustration cues.
- This module is the **consumer/orchestrator** that updates mastery and adapts tutor tone.

So yes: your friend triggers these endpoints, but you own and implement them.

---

## Integration 1: Question Engine -> Assessment Submit

### Endpoint

`POST /api/v1/assessment-submit`

### Purpose

Receive **ground-truth correctness** for a completed assessment item and update the shared BKT state.

### Current required payload

```json
{
  "user_id": "U123",
  "topic_id": "G6_S8_ELE_CIRCUITS",
  "is_correct": true
}
```

### Processing logic

1. Convert `is_correct` to binary label (`1` or `0`).
2. Call shared BKT engine: `predict_update(user_id, topic_id, label, None)`.
3. Return updated mastery and risk flag.

### Notes

- This is the **trusted** update path for mastery.
- If your teammate sends extra fields (difficulty, distractor, etc.), they are currently ignored unless you extend the schema.

---

## Integration 2: Engagement Module -> Frustration Cue Submit

### Endpoint

`POST /api/v1/engagement/frustration-cue`

### Purpose

Receive a normalized frustration signal and store it as the latest cue for that learner+topic.

### Current required payload

```json
{
  "user_id": "U123",
  "topic_id": "G6_S8_ELE_CIRCUITS",
  "frustration_score": 0.78,
  "source": "engagement_module_v1"
}
```

### Processing logic

1. Clamp score to `[0,1]`.
2. Map score to level:
   - `low` for `< 0.34`
   - `medium` for `0.34 .. 0.66`
   - `high` for `> 0.66`
3. Store latest signal in-memory for `(user_id, topic_id)`.
4. Return normalized score + mapped level.

### Important behavior

- This endpoint **does not** update BKT mastery.
- It updates tutor **tone control state** only.

---

## How sentiment-driven tutor adaptation now works

When `/tutor/hint` or `/tutor/hint-auto-topic` is called:

1. Tutor checks whether a stored frustration cue exists for `(user_id, topic_id)`.
2. If present, prompt tone guidance changes:
   - `high`: extra patient, short steps, gentler correction
   - `medium`: supportive and clear, lighter jargon
   - `low`: normal positive Socratic tone
3. Tutor response returns:
   - `frustration_level_used`
   - `frustration_score_used`

This creates the sentiment-driven feedback loop described in your proposal.

---

## Separation of responsibilities (recommended)

- **Assessment data** -> updates knowledge state (BKT mastery).
- **Engagement data** -> updates emotional context (tone adaptation).
- **Tutor dialogue interaction_score** -> optional noisy BKT update only when valid.

This keeps your architecture interpretable and aligned with your project report.

---

## Mapping from your friend’s planned quiz schema

Your friend can keep sending rich quiz metadata. Right now:

- Used directly for BKT:
  - `Topic ID` -> `topic_id`
  - `Accuracy` -> `is_correct`
- Not yet consumed in API contract (future extension candidates):
  - `Subtopic ID`
  - `Question Type`
  - `Difficulty Level`
  - `Response Time`
  - `Distractor Tag`
  - `Question Text` / `Correct Answer Text`
  - `Similarity Score` for short answers

If you want, next step is to add a `metadata` object to assessment submit so all fields are accepted while still using `is_correct` as the primary BKT label.
