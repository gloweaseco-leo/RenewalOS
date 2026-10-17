# RenewalOS Architecture Decision Record — 2026-10-17 (G0.2)

## 1. Product scope
Sports training renewal operations, not an all-in-one CRM. Contract status for 奥冠/aoguan-webapp is independent of this repository. Initial data is generated synthetic data only.

## 2. Current modular monolith

```
Browser (static/index.html + static/app.js)
  | HTTP localhost-only
  v
FastAPI (renewalos/main.py) -- CSV validation / followup commands
  |                       \
  v                        \ optional, real, configured HTTPS endpoint
SQLite (renewalos/db.py)   \--> LLM advice (renewalos/ai.py)
  ^
  |
Rules/experiment (renewalos/core.py)
```

Why Python/FastAPI now: small local demonstrator and SQLite with zero SaaS or vendor dependency. A redesign into Next.js, event bus, microservices, LLM orchestration or enterprise multi-tenancy is explicitly postponed.

## 3. Critical business invariants
1. `package_id` belongs to one learner; renewal's `learner_id` must match the package owner.
2. Experimental assignment is sticky by `store_id + family_id` (not global family alone).
3. The **control** arm never receives extra outreach suggestions from the product. Routine customer service is never withdrawn.
4. Followup history survives closure/recomputation; current opportunities are a view over business facts, not the transaction ledger.
5. Model advice is separate from rule advice and may only be requested in the AI arm; no model configured means an explicit 409, never a simulated AI answer.
6. Cash paid minus refunded is a fact; incremental profit/ROI requires frozen cohorts, valid comparison, observation period and cost evidence.
7. Permissions, customer contact compliance, deletion requests, production deployment and deep integrations are **not** solved by the local MVP.

## 4. Import sequence
`learners` → `packages` → `attendance` → `renewals` → recompute. Upserts are intentional for re-importing sanitized snapshots. The import endpoint validates header, row bounds, foreign keys, monetary precision and package/renewal ownership. Amounts are stored as integer cents.

## 5. Model execution
Not an autonomous agent. Structured numeric signals plus a minimal course type are sent to an operator-configured OpenAI-compatible HTTPS endpoint. Human reviewers approve/act on advice. No outbound client messages.

## 6. Experiment design G1 — open items
- Define frozen initial eligibility cohort, renewal window, exclusion policy, household clustering, cross-store repeat customers and intent-to-treat population.
- Controls receive the institution's pre-existing service; RULES arm uses deterministic alerts; AI arm adds actual model-authored action recommendations.
- Primary metric: eligible-family net paid renewals in a fixed window, refunded transactions netted, with contribution margin/cost per cohort.
- Report sample size, confidence intervals and limitations. Small samples cannot prove positive causality.
- Distinguish feature usage from model causal lift, and guard against moving the goalposts after experiment starts.

## 7. G1 security gate (BLOCKING)
Local-only middleware is a guardrail, not user login or tenant isolation. Do not expose on the network or use children's real identifiable data until identity/RBAC, lawful basis/guardian handling, DPIA/security reviews where applicable, import authorization, audit logging, backup/restore, retention and deletion have been implemented and independently tested.

## 8. G0.3 fact lineage (addendum)

`learners` → `packages` → `renewal_contracts` → `cash_events` (`refund_of` explicitly links refunds to a payment). Immutable new contract and event rows, idempotent replay, batch atomicity. Legacy `renewals` continues as a **separate, non-equivalent** source, preventing unsupported duplicate attribution.

`cohorts` → `renewal_cohort_members`: frozen store/day, source package uniqueness, fixed household arm, 45-day observation plus 14-day refund grace. Frozen events preserve the denominator; `recompute` updates operational opportunities only. Summaries are **descriptive and non-causal**. See `docs/RELEASE_G03.md`.
