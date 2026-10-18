# G0.4 evaluation protocol — why model compliance is not business value

## Question to answer

Does evidence-grounded LLM drafting materially help a trained staff member beyond an identical rule-triggered action, at acceptable added cost, without making the customer feel pressured?

## Offline paired review (requires real model to run, not yet executed)

1. Freeze 12 synthetic reference cases and versioned prompts. Evaluate at least 30 additional consent-safe, de-identified cases that have **no real customer identifiers** before claiming transferability.
2. Each case has two outputs: deterministic rule advice vs genuine model advice (different, randomly assigned A/B labels). Do not show raters which output is from an LLM. Present the same numeric evidence to both.
3. Two qualified reviewers independently grade on 1–5: (a) evidence consistency, (b) actionable specificity, (c) respect/service quality, (d) risk of unsupported inference, (e) added utility over baseline. Resolve differences with written evidence; record inter-rater agreement.
4. Unsafe suggestions are disqualified even if persuasive. Reviewers must not invent client intent. A machine gate pass alone does **not** count as helpful.
5. Report acceptance and rejection counts, pairwise preference percentages, cost per accepted output, latency, and human review minutes. Include missing cases and uncertainty.
6. Only after commercial permission, privacy review, cohort design and consent can field outcomes be compared by experimental arm. Cash facts and human ratings are not causal ROI.

## Scoring structure (draft, for authorized reviewers)

case_id | policy_version | model_id | output_sha256 | baseline_sha256 | reviewer_alias | grounded_1_5 | actionable_1_5 | respectful_1_5 | safety_violation | preferred_variant | reason | review_at

**Status: planned protocol. No human study and no external model experiment have been performed in this release.**
