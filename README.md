# RenewalOS — Sports Training Renewal Operations

**G0.7 independent localhost prototype** · no dependency on Aoguan's unsigned `aoguan-webapp` contract.

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

## G0.5 — Real-model comparison, no manufactured AI scores

G0.5 adds a 12-case frozen synthetic suite, provider-token and latency measurement, explicitly priced cost estimate, human A/B blind-review artifacts and independent reviewer score validation. Existing G0.4 opportunity operations remain unchanged, aside from benchmark telemetry. **No real API credentials were available for the included test run**, so its 56 passing tests and 12/12 rules baseline do not say anything about actual model performance or renewal profitability.

Try without API access:

```bash
python -m renewalos.benchmark_cli --offline --output-dir benchmark_runs/offline-demo
```

Run a genuine evaluation only when explicitly ready to incur cost; set your own provider's API key and model in the local environment, then follow [G0.5 release instructions](docs/RELEASE_G05.md). To protect blinding, keep the local private answer key away from human raters. All local reports in `benchmark_runs/` are ignored by Git.

## G0.6 — Complete synthetic renewal workbench loop (local development branch)

G0.6 adds the missing *operator-visible* journey: opportunity → followup → contract → simulated payment → archive → refund → reopened opportunity, with an inspectable transaction timeline. UI now supports active / archived / all records. Contracts and cash events can be recorded manually **only as explicitly synthetic facts**; they reuse the immutable G0.3 ledger and reject future events and over-collection. All new APIs remain behind the existing localhost-only boundary. No real payment provider is integrated.

To run the complete walkthrough: start locally; click “载入合成数据”; select a non-control opportunity; record a followup; create a synthetic contract and payment; switch to “已归档” to inspect the closed case and timeline; record refund if desired. Control group can receive normal transaction recording but cannot receive incremental marketing followups.

Run `python -m pytest -q` and `node --check static/app.js`. **DO NOT deploy this branch to Vercel**: there is no authentication, user authorization, real multi-tenant storage, privacy lifecycle or production API gateway. The GitHub production branch is intentionally not changed by this stage.

See `docs/RELEASE_G06.md`.


## G0.7 — 销售待办与人工任务闭环（本地）

- 机会详情：仅非对照组、已同意联系且仍活跃的合成学员可分配任务；防止一机会重复派单。
- 左侧「销售待办」：按门店/员工代号筛选，查看今日、逾期、已结束任务；修改负责人、截止日与进度。
- 在任务中填写人工跟进，旧机会详情跟进记录自动与任务状态同步；操作事件按时间保存。
- 成交归档后任务仍保留，但不允许继续定向营销；退款且业务重新满足条件，可写明原因重新开启。
- **无用户认证与正式门店数据权限**，责任人只是本地演示代号；不触达真实客户、不接入生产支付，不可公网部署。

详情见 [`docs/RELEASE_G07.md`](docs/RELEASE_G07.md)。
