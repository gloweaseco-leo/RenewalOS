# RenewalOS G0.4 — AI suggestion quality gate

Date: 2026-10-17 · Scope: local synthetic demonstration only · Version 0.4.0.

## What shipped

1. **Structured real-model response:** action_code, evidence_keys, message, uncertainty, no free-form unvalidated advice. Only anonymous numeric business signals leave the machine; imported course labels are not sent.
2. **Machine validation:** fixed action safety precedence, required evidence, constrained output size, prohibited promotions/autosends, basic leakage checks. A rejected model response cannot overwrite previously accepted content. **This guardrail is incomplete**: subtle hallucinations may still pass, hence a human check is mandatory.
3. **Review state:** pending_review -> approved / rejected; separate review ledger distinct from customer followups. No autonomous customer contact.
4. **Staleness:** signal fingerprint and policy version are bound to advice. Old G0.3 free-text drafts are not displayed. Advice generated from changed signals is withheld. Recompute does not delete historical attempts/reviews.
5. **Benchmarks:** 12 frozen synthetic rule cases and explicitly user-triggered real-model machine checks (up to 4 cases per request); no fake vendor scores. 409 if model is not configured.
6. **UI:** quality panel; real-model audit state and explicit human decision. No prompt injection from imported course labels is sent to LLM.

## Commands

```bash
python -m pip install -e '.[test]'
python -m pytest -q
node --check static/app.js
python -m uvicorn renewalos.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 then click **载入合成数据**. Offline baseline does not require external calls. For genuine model checks supply `RENEWAL_AI_BASE_URL`, `RENEWAL_AI_API_KEY`, `RENEWAL_AI_MODEL` using local environment secrets. Do **not** put keys in GitHub. Data and products remain synthetic.

## Release criteria and limits

- Must pass full G0.2+G0.3+G0.4 regression, Python and browser JavaScript syntax checks.
- Report 12-case baseline as **machine policy tests**, not AI quality measurements.
- No real model quality score without a real call. A local fake/stub is always labeled as such.
- No comparative improvement claim without blinded human evaluation against rule output and subsequent real experiment with approved data, adequate sample and contribution costs.
- No network/public deployment, real identifiable minors or multi-company operations. Current prototype lacks login/RBAC, production isolation, encryption, retention and incident procedures.

## Deferred

Churn prediction, personalized discount optimization, automated WhatsApp/WeChat messaging, model fine-tuning, production identity/audit, uplift causal inference, commercial billing and full SaaS connectors.