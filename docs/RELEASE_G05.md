# RenewalOS G0.5 — Real-model evaluation harness (2026-10-17)

**State:** evaluation harness implemented and verified with local stubs. No live model credentials were available during this release. **No externally verified model results, human quality results, revenue attribution or ROI are claimed.**

## New deliverables

- `renewalos/benchmark_lab.py`: frozen 12-case synthetic evaluation, hash-bound fixture suite, model policy acceptance, latency, optional provider token usage and conditional API cost estimate.
- `renewalos/benchmark_cli.py`: explicit-cost CLI; offline baseline without network; live bounded model calls only after opt-in, environment configuration and user-chosen case count.
- `renewalos/ai.py`: retains the existing two-value `suggest` API; adds telemetry-enabled `suggest_with_telemetry` for benchmark calls.
- `POST /api/quality/benchmark`: retains 4-call maximum and now returns timing and token usage when provided. No private answer key is sent through HTTP.
- Three local artifacts: `machine_report.json`, `blind_review_template.csv`, `private_answer_key.json`. Answer key is separate and created with owner-only permissions when possible; model raw failures are not stored.
- `score_human_reviews` validates two independent reviewers, each submitting consistent complete forms. It never automatically claims business uplift or statistical superiority from a small review.

## Offline verification

```
python -m pip install -e '.[test]'
python -m pytest -q
node --check static/app.js
python -m renewalos.benchmark_cli --offline --output-dir benchmark_runs/offline-first
```

The offline baseline is NOT a model benchmark. It verifies machine rules on invented numbers only. The configured model is not contacted by default.

## Genuine model benchmark (explicit billable calls)

Set `RENEWAL_AI_BASE_URL` (HTTPS, including `/v1`), `RENEWAL_AI_MODEL` and `RENEWAL_AI_API_KEY` in the local shell. Never commit secrets or identify real learners.

```
python -m renewalos.benchmark_cli \
  --acknowledge-live-cost --max-cases 12 \
  --input-price-per-million YOUR_PRICE \
  --output-price-per-million YOUR_PRICE \
  --output-dir benchmark_runs/providerA-20261017-01
```

Prices use the **same unspecified currency** as the submitted model pricing. They are operator-entered; if omitted or if provider token usage is absent, cost is `null`, not zero. Real API calls may cost money even if an output is rejected. The CLI uses up to twelve sequential synthetic requests; UI remains capped at four. A fresh directory is required to prevent rewriting a previous run.

## Human blinded review protocol

Share **only** `blind_review_template.csv` with two independent qualified raters. Each fills scores 1–5 for groundedness, actionability and respectful service, `yes/no` safety violations and `A/B/tie` preference with a rationale. Keep `private_answer_key.json` out of raters' sight. Save as e.g. `reviewer1.csv` and `reviewer2.csv`.

```
python -m renewalos.benchmark_cli \
  --score-review benchmark_runs/providerA-20261017-01/reviewer1.csv benchmark_runs/providerA-20261017-01/reviewer2.csv \
  --answer-key benchmark_runs/providerA-20261017-01/private_answer_key.json
```

Incomplete or only one-reviewer results are marked `complete=false` and cannot be interpreted as comparative quality evidence. Machine-gate rejected cases are not put into review A/B sheets and remain counted as failures. Machine compliance is a prerequisite, not a benefit claim. Because the policy requires both variants to follow the same action class, this G0.5 experiment principally tests **quality of expression and evidence handling**, not a superior decision policy.

## Further investment gate

Do not invest in production AI recommendation logic merely on a higher preference share. A next-stage decision requires: (i) model safety compliance and reasonable error rate, (ii) two genuinely blinded reviewers, (iii) added decision usefulness beyond rules at acceptable unit cost, and ultimately (iv) authorized data and prospective customer experiment for any incrementality claim. Rules-first remains the default.

## Known limits

Current prototype lacks production authentication, RBAC, tenant separation, personal data management, real customer datasets and sound causal evaluation. No automatic client communications, discounts or claims of churn prediction.
