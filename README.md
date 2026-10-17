# RenewalOS — Sports Training Renewal Operations

**G0.2 independent localhost prototype** · no dependency on Aoguan's unsigned `aoguan-webapp` contract.

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

CSV import sequence: learners → packages → attendance → renewals → **重新计算**. Exact field names: see `docs/PRODUCT_SCOPE.md` and the app UI. Local SQLite database `renewalos_local.db` is created on first startup and is git-ignored. Backup database files before upgrading; G0.2 supports schema migration from G0.1.

## Security and evidentiary limits

- Synthetic or lawfully authorized, fully pseudonymized demonstration data only. No real children's personal identifiers, phone numbers or private notes.
- Local-only prototype has **no accounts, production tenancy/RBAC, retention or privacy management**; it is not a production SaaS.
- No customer auto-messages, pricing decisions or autonomous renewals.
- Control arm does not get extra targeted advice; normal customer service continues for every arm.
- Actual paid/refunded ledger is not a causal estimate. ROI is explicitly unavailable until frozen eligible cohorts, adequate observation windows, contribution costs and valid comparison evidence exist.

Read `docs/ARCHITECTURE.md` and `docs/RELEASE_G02.md` for the current system architecture, design constraints and known gaps.