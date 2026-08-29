# PHASE 2 Roadmap - Learner Profile Analytics and Socratic Support

This document proposes phase-2 enhancements for the full component so it better matches the outcomes promised in `DOCS/R26-SE-003_IT22055262_LIYAUDEEN D.H.pdf`.

It is written as an execution plan you can use for implementation, demos, and final evaluation reporting.

---

## 1) Why Phase 2

Your current implementation already delivers a strong baseline:

- interpretable BKT mastery tracking,
- Socratic RAG tutor with policy-gated chat updates,
- frustration-aware tone adaptation,
- teacher dashboard with at-risk analytics,
- API-driven integration points.

Phase 2 focuses on closing the remaining proposal commitments:

1. strengthen predictive rigor (especially PFA + calibrated risk),
2. formalize evaluation metrics (AUC/RMSE/latency/pedagogical rubrics),
3. improve production-readiness (privacy, monitoring, reliability, scaling),
4. improve cross-component data interoperability (assessment + engagement + learning path).

---

## 2) Proposal Commitments -> Phase 2 Deliverables

### Objective 1: Interpretable Analytics Engine (BKT + PFA)

Current status:

- BKT is implemented and explainable (`prior`, `learn`, `guess`, `slip`, `forget`).
- Live update stabilization exists (damping, caps, step bounds).
- PFA is not yet first-class in the runtime pipeline.

Phase-2 deliverables:

1. Add a **PFA feature layer** per learner-topic:
   - cumulative successes/failures,
   - recency-weighted attempts,
   - opportunity count.
2. Expose **hybrid cognitive profile** endpoint:
   - BKT `P(L)`, slip/guess + PFA score side-by-side.
3. Add **calibration report**:
   - reliability curves and Brier score for BKT and hybrid model.
4. Add **concept drift checks**:
   - alert if prediction quality degrades over rolling windows.

Success criteria:

- AUC >= 0.75 on held-out traces (as proposed),
- RMSE trend stable or improved against current baseline,
- calibration error reduced after hybrid fusion.

---

### Objective 2: RAG-based science tutoring pipeline

Current status:

- retrieval is integrated and prompt-grounded,
- safety constraints are encoded in system instructions,
- output is schema-constrained JSON.

Phase-2 deliverables:

1. Add **retrieval quality instrumentation**:
   - top-k chunk IDs, similarity scores, retrieval latency.
2. Add **grounding audit mode**:
   - store minimal evidence snippets used for each hint.
3. Add **curriculum coverage matrix**:
   - per topic: chunk count, weak coverage gaps, stale chunks.
4. Add **fallback hierarchy**:
   - if retrieval low-confidence, force narrower conservative hint template.

Success criteria:

- lower hallucination/unsupported statement rate in human review,
- stable retrieval latency under load,
- measurable coverage across all targeted Grade 6-9 topics.

---

### Objective 3: Socratic prompting framework

Current status:

- mastery-conditioned mode selection exists (`scaffold`, `balanced`, `nudge`),
- strict non-direct-answer behavior exists,
- analogy-guided prompt style exists.

Phase-2 deliverables:

1. Build a **prompt versioning registry**:
   - version ID on each response,
   - changelog of rule adjustments.
2. Add **Socratic quality rubric scorer** (human-in-the-loop):
   - no direct answer leakage,
   - misconception correction quality,
   - appropriateness of follow-up question,
   - grade-level readability.
3. Add **A/B testing harness** for prompt variants:
   - compare student progress and rubric scores.
4. Add **auto-guard**:
   - reject/rewrite replies that violate one-question or no-direct-answer policy.

Success criteria:

- reduced direct-answer leakage,
- improved rubric score consistency,
- measurable gain in follow-up correctness rates.

---

### Objective 4: Sentiment-aware tutoring logic

Current status:

- frustration signal ingestion and tone adaptation exist,
- separation from mastery updates is clear.

Phase-2 deliverables:

1. Upgrade from single latest cue to **short temporal emotion model**:
   - smoothed frustration trend + volatility.
2. Add **engagement-aware pacing** policy:
   - high frustration -> shorter prompts, smaller cognitive jumps.
3. Add **frustration intervention recommendations** to teacher analytics:
   - suggested teacher action cards.
4. Add **explainability tags** in chatbot output:
   - why tone was adapted (without exposing sensitive internals to students).

Success criteria:

- reduced abandonment/early-exit pattern during difficult topics,
- better student-rated support during high-frustration sessions.

---

### Objective 5: Predictive teacher alert dashboard

Current status:

- mastery matrix and at-risk alerts exist with criteria and weighted scoring,
- student profile analytics endpoint exists.

Phase-2 deliverables:

1. Add **unit-failure probability forecasting** horizon:
   - probability of underperformance in upcoming unit, not only current topic risk.
2. Add **misconception trajectory panel**:
   - recurrent distractor families by topic over time.
3. Add **intervention efficacy tracker**:
   - before/after mastery and risk movement after teacher actions.
4. Add **class segmentation views**:
   - mastery clusters, emotional-risk clusters, pacing groups.

Success criteria:

- teachers identify at-risk learners earlier,
- post-intervention risk score reduction observable in dashboard.

---

## 3) Cross-cutting engineering improvements

These improvements strengthen reliability and align with NFRs in your proposal.

### A) Evaluation and experiment pipeline

1. Add `evaluation/` scripts for:
   - AUC, RMSE, precision-recall,
   - Brier score / calibration plots,
   - latency p50/p95/p99.
2. Add frozen benchmark datasets/splits.
3. Add repeatable experiment config files and result artifacts.

### B) Observability and operations

1. Add structured logs for all core endpoints.
2. Add metrics counters/timers (request count, latency, errors, BKT updates skipped).
3. Add alerting thresholds for API failures and latency regressions.

### C) Security and privacy hardening

1. Add explicit PII scrubber before persistence and logs.
2. Add retention policy for interaction logs and event DB.
3. Add privacy section in API docs (what is stored, for how long, why).

### D) Data contracts between components

1. Publish versioned JSON schemas for:
   - assessment events,
   - engagement events,
   - learner profile exports.
2. Add backward-compatible validation and contract tests.

### E) Performance and scalability

1. Cache retrieval embeddings/chunk metadata aggressively.
2. Add async worker path for heavy replay analytics.
3. Add load test scenario for classroom-scale concurrent sessions.

---

## 4) Suggested implementation order (practical)

### Sprint 1 (analytics foundation)

- Implement PFA feature computation and hybrid profile endpoint.
- Add evaluation scripts for AUC/RMSE/calibration.
- Add schema definitions for incoming events.

### Sprint 2 (tutor quality + safety)

- Prompt versioning and rubric scoring pipeline.
- Response auto-guard (no direct answer policy checker).
- Retrieval instrumentation and grounding audits.

### Sprint 3 (dashboard intelligence)

- Unit-level failure probability model.
- Misconception trend and intervention effect panels.
- Class-level segmentation visualizations.

### Sprint 4 (production readiness)

- Observability metrics and alerts.
- Privacy controls and retention policies.
- Load testing and optimization pass.

---

## 5) Metrics board for final dissertation/demo

Track these in one table for Progress 2 + final viva:

1. **Predictive quality**
   - AUC, RMSE, Brier score, calibration error.
2. **Tutor quality**
   - Socratic rubric average, direct-answer leakage rate, grounding pass rate.
3. **Engagement and empathy**
   - high-frustration session recovery rate, average session length under stress.
4. **Teacher usefulness**
   - precision@k for at-risk alerts, intervention impact delta.
5. **System performance**
   - end-to-end latency p50/p95/p99, error rate, uptime.

---

## 6) Risks and mitigations (Phase 2)

1. **Risk:** PFA adds complexity without clear gain.  
   **Mitigation:** keep BKT as base; run ablation tests and deploy hybrid only if metrics improve.

2. **Risk:** Prompt updates hurt consistency.  
   **Mitigation:** prompt versioning + A/B tests + rollback switch.

3. **Risk:** Added analytics slows response times.  
   **Mitigation:** async background analytics and strict online inference budget.

4. **Risk:** Persistent logs increase privacy exposure.  
   **Mitigation:** data minimization, anonymization, retention windows, audit trails.

---

## 7) Definition of "Phase 2 complete"

Phase 2 is complete when all conditions below are met:

1. Hybrid BKT+PFA profiling is implemented and evaluated.
2. Tutor has measurable rubric-backed quality improvements with versioned prompts.
3. Dashboard includes forward-looking failure probability and intervention tracking.
4. Evaluation artifacts (metrics + scripts + reports) are reproducible.
5. Reliability/privacy/scalability controls are documented and tested.

---

## 8) Optional commercialization-ready extensions

If you want alignment with your freemium model section:

- **Basic tier:** mastery heatmap + limited hints/day.
- **Standard tier:** predictive alerts + full analytics + higher hint quota.
- **Premium tier:** unlimited hints + sentiment adaptation + advanced intervention analytics + API access.

These can be implemented as feature flags at the API layer.

