"""Explicit local benchmark runner. Never scheduled automatically."""
import argparse
import json
import os
from pathlib import Path
from .ai import suggest_with_telemetry
from .benchmark_lab import evaluate_model,write_artifacts,score_human_reviews
from .evaluation import baseline_report


def main(argv=None):
    p=argparse.ArgumentParser(description='RenewalOS G0.5 synthetic model benchmark')
    p.add_argument('--output-dir',default='benchmark_runs/g05')
    p.add_argument('--offline',action='store_true',help='write only the deterministic baseline; no model calls')
    p.add_argument('--acknowledge-live-cost',action='store_true',help='explicit confirmation of billable provider calls')
    p.add_argument('--max-cases',type=int,default=4)
    p.add_argument('--input-price-per-million',type=str)
    p.add_argument('--output-price-per-million',type=str)
    p.add_argument('--score-review',nargs='+',metavar='REVIEWER_CSV')
    p.add_argument('--answer-key',help='private_answer_key.json required for scoring completed reviews')
    args=p.parse_args(argv)
    if args.score_review:
        if not args.answer_key:p.error('--score-review requires --answer-key')
        key=json.loads(Path(args.answer_key).read_text(encoding='utf-8'))
        result=score_human_reviews([Path(f).read_text(encoding='utf-8') for f in args.score_review],key)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['complete'] else 4
    output=Path(args.output_dir)
    if args.offline:
        output.mkdir(parents=True,exist_ok=True)
        target=output/'rule_baseline.json'
        if target.exists():p.error('refuse to overwrite baseline report')
        target.write_text(json.dumps(baseline_report(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(str(target));return 0
    if not args.acknowledge_live_cost:p.error('real-model benchmark requires --acknowledge-live-cost')
    if not all(os.getenv(k) for k in ('RENEWAL_AI_BASE_URL','RENEWAL_AI_API_KEY','RENEWAL_AI_MODEL')):
        p.error('live model not configured; no calls made, use --offline')
    try:
        report,blind,key=evaluate_model(suggest_with_telemetry,limit=args.max_cases,
            input_per_m=args.input_price_per_million,output_per_m=args.output_price_per_million)
        paths=write_artifacts(output,report,blind,key)
    except (ValueError,FileExistsError) as e:p.error(str(e))
    print(json.dumps({'summary':{k:report[k] for k in ('models','cases_tested','machine_accepted','blind_review_pairs','estimated_total_api_cost')},'artifacts':paths},ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
