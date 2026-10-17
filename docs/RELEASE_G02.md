# G0.2 Release Notes

**Development readiness:** local standalone synthetic-data MVP. Not production-approved.

### Resolved from G0.1
- Rule and model advice are hidden from the control arm to reduce experimental contamination.
- Historical followups and resolved opportunities remain intact after recomputation (soft archival).
- Household assignment now scopes its key to each store and keeps sticky assignment.
- Reject renewal imports when the learner does not own the referenced package.
- Restrict browser writes by host/origin for localhost demonstration.
- V0.1 SQLite schema can migrate non-destructively to V0.2 (with backup strongly recommended).
- Followup history available at `GET /api/followups/{opportunity_id}`.
- Financial outcome: net paid remains **not causal**. No fabricated ROI.

### Verification performed
- `python -m pytest -q` (15 tests passing)
- `node --check static/app.js` (syntax passing)

### Known limitations / P1
- Experiment frozen cohort, consent withdrawal, source traceability, pricing/contract recognition, cost attribution and model effect are not yet ready.
- SQLite and local UI have no user login or tenant-level access controls.
- There is no automatic backup/delete retention lifecycle for legitimate personal information.
- This release must not be deployed to internet or used with real identifiable children's records.