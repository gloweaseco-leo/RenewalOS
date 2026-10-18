# G0.6 — Local business loop release & acceptance

## Why

Previous Vercel URL does not represent an accepted deployment: no Vercel entry, localhost-only FastAPI middleware, local SQLite, and no auth. G0.6 does **not** loosen these safety defaults. Instead it completes the missing executable business journey while staying local.

## Added

- An **active/archived/all** opportunity selector. Paid opportunities remain inspectable and preserve the historic followup and transaction timeline.
- An in-workbench **synthetic contract creation** action, using the original source package. No separate learner ID is supplied by the browser; the server resolves ownership.
- **Synthetic payment/refund** registration, with immutable event IDs, deduplication, original payment refund linkage, and a per-contract UI-level overcollection guard.
- Payment re-computes opportunities: net positive payment archives; full refund can re-open when eligibility persists. Refund does **not** erase a transaction or the original followup history.
- Human followup history visible in the case detail. Control group can record normal outcomes but cannot receive additional product-driven outreach.
- 4 integration test scenarios on top of the existing 56 G0.5 tests.

## Operations and non-claims

All customer details and transactions must be **synthetic**. UI and API explicitly say simulated payments are not verified third-party receipts. Recording a transaction is not a causal AI-effect measurement. The existing G0.3 fixed-cohort result remains descriptive with ROI null.

Endpoints:

- `GET /api/opportunities?include_archived=true`
- `GET /api/demo/sales/{package_id}`
- `POST /api/demo/sales/contracts` `{source_package_id, contract_id, signed_on, amount_cny}`
- `POST /api/demo/sales/payments` `{contract_id, event_id, event_on, amount_cny}`
- `POST /api/demo/sales/refunds` `{payment_event_id, event_id, event_on, amount_cny}`

Event/contract IDs supplied by UI are safe replay keys. Reusing a key with different content is rejected. The locally generated IDs are not payment gateway transaction IDs.

## Remaining before a *public* MVP

**No external deployment approved.** Priority blockers:

1. Authentication, session management, server-enforced tenant/store RBAC, least privilege.
2. Privacy and security: consent boundaries; minors data; event audit logs; encrypted storage/backups; retention/deletion and incident handling.
3. Persistent PostgreSQL or equivalent; secure migrations and tenancy-aware transaction boundaries; no SQLite file in serverless deployment.
4. An approved staging environment, secure backend routing and environment separation; Vercel URL requires an explicit build/runtime contract.
5. Production payment truth must come from a customer-authorized system or independently verified provider; the G0.6 manual simulation **must remain disabled** for actual tenants.
6. Practical evidence: real-model double-blind assessment and eventually a valid actual-ROI experiment. Neither is proven yet.

## Acceptance

`pytest -q` 60 tests; `node --check static/app.js`; FastAPI smoke test for home, script and API. CI run must pass before branch merge. Review release on feature branch; do not auto-deploy to the existing Vercel public alias.
