# G1-C — Authenticated synthetic PostgreSQL business workflow

**State:** development PR; CI PostgreSQL acceptance required. This is NOT a public-cloud or customer-data release.

## Architecture and scope

G1-A local SQLite credentials and expiring bearer sessions remain in `secure_local` mode. The G1-C REST endpoints use the verified principal from that session, **plus** a matching PostgreSQL organization/store membership and matching role. No request body can supply actor identity. `RENEWAL_PG_APP_DSN` enables the PG business surface; without it the new endpoints return 503 instead of falling back to SQLite. The new route prefix is `/api/v1/orgs/{org_id}/stores/{store_id}`.

- `GET /opportunities`, `GET /tasks`: managers see the store, staff only assigned cases/tasks.
- `POST /tasks`: manager assigns a previously unassigned opportunity to an enabled staff member. Client-generated IDs support identical-retry idempotency.
- `POST /followups`: the assignee (or manager) records a **synthetic** contact event; no automatic messaging.
- `POST /contracts`: manager records synthetic renewal contract; *control* customers can be recorded as natural sales without marketing tasks.
- `POST /cash-events`: manager records synthetic payment/refund facts; database trigger rejects overpayment, invalid refund and cross-tenant transactions.
- `GET /management`: manager-only pipeline snapshot and synthetic net cash; `incremental_roi` always null.

G1-C migration `002_business_write.sql` adds experiment arm (new rows default to **control**), append-only audit events and restrictive actor-level write policies. The local test migration runner refuses to operate outside ephemeral CI; production migrations need a separately reviewed procedure.

## Real DB CI acceptance

1. Disposable PostgreSQL 16 service is provisioned by GitHub Actions.
2. Apply 001 core schema; provision disposable application role; apply 002 restricted write policy.
3. Run all G0/G1-A/G1-B regression tests alongside end-to-end FastAPI authenticated G1-C tests.
4. Enforce isolation for cross-org, cross-store, mismatched roles and non-owner employee.
5. Exercise manager assignment → staff followup → synthetic contract → payment/refund → audit, repeated requests, overpayment, control-arm block and fail-closed configuration.

## Important release blockers

- The public Vercel deployment **cannot** be used for this branch. The entire flow is bound to `127.0.0.1` only.
- G1-A login credentials/sessions remain in SQLite, separate from PG business data. This transitional dual-membership guard does **not** constitute production IAM or a durable authentication system.
- Real customer data, including identifiable children and guardian notes, must not be imported. This is a synthetic-only local development surface.
- No payment gateway, webhook or financial reconciliation has been integrated. All PG write routes intentionally write `provenance='synthetic'`.
- Customer-outreach authorization is only a Boolean eligibility flag; full consent history, opt-out, retention rules and experiment freezing remain future work.
- The 002 migration has not been executed in any production database. No migrations should be auto-applied on service startup.

## Follow-up

For production-readiness, migrate identity/session state or use OIDC, eliminate the local SQLite dependency, implement verified provider payment ingestion and staff-visible audited business UX, and run browser-over-HTTP security acceptance behind TLS with genuine tenant partitions. Merge only after these gates.
