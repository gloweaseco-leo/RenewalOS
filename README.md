# RenewalOS — Sports Training Renewal Operations

**G0.4 independent localhost prototype** · no dependency on Aoguan's unsigned `aoguan-webapp` contract.

A small working loop: sanitized CSV data → explainable renewal signals → household-level experimental arms → staff-recorded followup → actual net paid facts. It **does not** invent AI uplift/ROI; real model advice only runs with a configured endpoint in the AI arm.

## Run

Python 3.10+:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn renewalos.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and click **载入合成数据**. Do not expose to the public network.

## Test

```bash
pip install -e '.[test]'
python -m pytest -q
node --check static/app.js
```

## Data interfaces

CSV import sequence: learners → packages → attendance → renewals → **重新计算**. Exact field names: see `docs/PRODUCT_SCOPE.md` and the app UI. Local SQLite database `renewalos_local.db` is created on first startup and is git-ignored. Backup database files before upgrading; G0.3 supports non-destructive SQLite migration from G0.1/G0.2.

## Security and evidentiary limits

- Synthetic or lawfully authorized, fully pseudonymized demonstration data only. No real children's personal identifiers, phone numbers or private notes.
- Local-only prototype has **no accounts, production tenancy/RBAC, retention or privacy management**; it is not a production SaaS.
- No customer auto-messages, pricing decisions or autonomous renewals.
- Control arm does not get extra targeted advice; normal customer service continues for every arm.
- Actual paid/refunded ledger is not a causal estimate. ROI is explicitly unavailable until frozen eligible cohorts, adequate observation windows, contribution costs and valid comparison evidence exist.

Read `docs/RELEASE_G03.md` (current delivery), `docs/ARCHITECTURE.md`, and `docs/RELEASE_G02.md` (historical baseline).

## G0.3 — Auditable renewal facts (new)

- Import `contracts` then `cash_events` with the exact headers described in `docs/RELEASE_G03.md`. Existing `renewals` are legacy and **must not be summed with the new contract-linked ledger**.
- Visit **经营验证** and freeze today's eligible cohort for a store. The control/rules/AI arms are snapshotted at enrollment. No retrospective freeze or auto-claimed uplift.
- Open an opportunity and request its source-package lifecycle timeline. A payment is a fact; an AI-caused renewal is not yet established.
- Unit/integration verification: `python -m pytest -q` (24 tests); `node --check static/app.js`.


## G0.4 — Evidence-grounded advice quality gate

- `GET /api/quality/baseline`: reproducible 12-case *deterministic synthetic* rules baseline.
- `POST /api/quality/benchmark` `{ "max_cases": 4 }`: **explicit, billable** actual-model evaluation on up to 4 synthetic cases. No model API configured => HTTP 409. Machine gates are not a human quality evaluation.
- AI experiment arm only: `POST /api/opportunities/{id}/ai-advice`. Model must return structured JSON with action, evidence keys, uncertainty and draft. Unverifiable advice is rejected and the rule recommendation remains.
- Human reviewer: `POST /api/opportunities/{id}/ai-review`, `{"reviewer":"staff-alias","decision":"approved"}` or `rejected`. Reviews are recorded separately from actual customer contact and **do not count as followups**.
- Suggestions become stale when source signals change. Original audit attempts and review decisions are retained; pre-G0.4 unvalidated model drafts are suppressed.

**No real AI model was called during included automated tests.** Tests use explicit stubs. The 12/12 synthetic baseline pass rate does not establish model superiority, outreach effect, or ROI. See `docs/RELEASE_G04.md` and `docs/HUMAN_EVAL_PROTOCOL.md`.
