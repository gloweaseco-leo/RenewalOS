## G1-E · PostgreSQL 统一身份（本地开发）

身份凭据、会话和机构/门店授权现在可全部保存在 PostgreSQL，不再依赖本机 SQLite。
配置 `RENEWAL_AUTH_BACKEND=postgres` 时，身份与业务 DSN 必须使用**不同权限的数据库角色**；旧仅含门店ID的接口禁用，前端显示 `机构 / 门店` 唯一授权范围。GitHub CI 负责实际 TCP HTTP + PostgreSQL 端到端回归；依然 **不得公网部署或使用真实儿童客户数据**。详见 `docs/RELEASE_G1E.md`。

# RenewalOS — Sports Training Renewal Operations

**G0.8 independent localhost prototype** · no dependency on Aoguan's unsigned `aoguan-webapp` contract.

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

## G0.8 — Manager process review (localhost-only)

Read-only **门店经营复盘** provides store-filtered current-stage counts, distinct process milestones, staff task workload, exception review and traceable case navigation. This is **not** a causal conversion funnel, verified processor settlement or ROI. GET `/api/management/overview` only works under the existing localhost host restrictions. See `docs/RELEASE_G08.md`.

## G1-A 安全本地预览（alpha，不可上公网）

增加 `RENEWAL_RUNTIME_MODE=secure_local` 的**默认拒绝**API运行模式、密码散列和可撤销会话、门店及员工级只读访问、经理角色控制、独立本地登录页；旧版不安全的演示业务路由全部禁用。当前仍为SQLite本地预览，**未完成PostgreSQL和正式多租户上线能力**。

详见 [`docs/RELEASE_G1A.md`](docs/RELEASE_G1A.md) 里的初始化/登录操作和 [`docs/ADR_G1_DATA_ARCHITECTURE.md`](docs/ADR_G1_DATA_ARCHITECTURE.md) 的下一步数据库迁移条件。



## G1-B PostgreSQL multi-tenant foundation (not yet integrated into public API)

PostgreSQL 16 migration, real-database RLS / composite-foreign-key / cash-event invariant tests,
scoped read adapter, and CI with isolated PostgreSQL service are under
`migrations/postgres/`, `renewalos/pg_store.py`, `tests/test_g1b_postgres.py`.
See `docs/RELEASE_G1B.md`. Legacy `secure_local` remains SQLite-only, localhost-only;
no real customer data and no production cloud deployment.

## G1-C (development branch) — PostgreSQL authenticated business writes

See [G1-C release/limits](docs/RELEASE_G1C.md). New local-only `/api/v1/orgs/{org}/stores/{store}/` endpoints support manager task assignment, assigned-staff followup, synthetic contract and append-only payment/refund, and manager reporting. Requires `RENEWAL_RUNTIME_MODE=secure_local` plus `RENEWAL_PG_APP_DSN` and **matching** store roles in G1-A local auth and PostgreSQL. 002 migration is tested only on disposable CI database. No real data or public hosting.

## G1-D (development) — 登录后的PostgreSQL经营工作台

本地 `secure_local` 登录页现在提供基于受认证PG业务接口的机会、销售任务、经理复盘及合成续费合同/现金事件操作。需要填写机构代号并选择授权门店；输入机构ID不能替代服务端权限校验。员工只能读取被分配案件的跟进记录，资金信息仅经理可见，仍不得公网使用。详情见 [G1-D发布与限制](docs/RELEASE_G1D.md)。

## G1-F real-browser CI acceptance

GitHub CI starts PostgreSQL 16, applies migrations and separate DB-role grants, runs Python 3.11/3.12 regression plus real TCP HTTP tests, and on Python 3.11 launches actual Playwright Chromium against loopback Uvicorn to click through the manager/staff renewal workflow. Results must come from the live CI run (local browser navigation may be blocked by the execution environment). See `docs/RELEASE_G1F.md`. Public deployment and production customer data remain prohibited.

## G1-G｜公网禁用的上线防护与恢复演练

G1-G新增生产部署强制NO-GO、双最小权限PG连接校验、`/api/ready`本地就绪检查、`python -m scripts.release_audit_g1g`审计和GitHub CI中仅使用合成数据库的`pg_dump`/`pg_restore`恢复对账。**不允许公网、不得接入真实学员或支付数据。**见 `docs/RELEASE_G1G.md`。


## G1-H｜企业OIDC身份接入原型（本地合成测试，仍禁止公网）

`RENEWAL_AUTH_BACKEND=oidc` 明确关闭密码登录，采用OIDC授权码 + S256 PKCE、
一次性state + HttpOnly浏览器绑定Cookie、nonce、RS256/JWKS、issuer/audience、MFA声明校验。
**只有管理员已映射的(issuer,sub)能登录；邮箱/昵称绝不自动生成门店权限。**
执行 `python -m scripts.pg_apply_g1h` 仅支持一次性GitHub CI测试数据库。
详见 `docs/RELEASE_G1H.md`。生产/预发公网仍为`NO_GO`。


## G1-I OIDC provider interoperability (not public deployment)

`python -m scripts.probe_provider_g1i` 检查**管理员预置**OIDC发行者的真实元数据、S256及签名公钥。
GitHub CI以一次性Keycloak容器执行真正的HTTPS授权码交换，**纯密码认证无MFA被拒绝**。
参见 `docs/RELEASE_G1I.md`、`deploy/preprod/README.md`。
现有`release_gate`的生产/预发NO-GO不可放宽。

## G1-J (draft): MFA acceptance and irreversible revocation

- `migrations/postgres/005_session_revocation.sql`: all prior sessions revoked on identity, role, membership or OIDC binding changes.
- `scripts/keycloak_mfa_g1j.py`: isolated real Keycloak password+TOTP positive flow, never a production credential.
- **No public or client production deployment**. See `docs/RELEASE_G1J.md`.
