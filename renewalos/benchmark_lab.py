"""G0.5 reproducible, synthetic-only, blinded model-versus-rules evaluation.

Safety: this is NOT a churn efficacy or revenue-uplift estimate. Model calls are
explicit, bounded and billable. Rejected model text is not persisted.
"""
import csv
import hashlib
import hmac
import io
import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from .evaluation import CASES
from .quality import POLICY_VERSION, rule_output, grade_output

SUITE = 'g04-fixed-synthetic-v1'
SCHEMA_VERSION = 'g05-benchmark-v1'
FIELDS = ('case_id','variant_A','variant_B','reviewer_alias','A_grounded_1_5',
          'B_grounded_1_5','A_actionable_1_5','B_actionable_1_5',
          'A_respectful_1_5','B_respectful_1_5','safety_violation_A',
          'safety_violation_B','preferred_variant','reason')


def suite_digest():
    canonical = json.dumps(CASES,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _safe_usage(telemetry):
    telemetry=telemetry if isinstance(telemetry,dict) else {}
    output={}
    for key in ('prompt_tokens','completion_tokens'):
        value=telemetry.get(key)
        output[key]=value if type(value) is int and value>=0 else None
    latency=telemetry.get('latency_ms')
    output['latency_ms']=round(latency,2) if type(latency) in (int,float) and 0<=latency<=3600000 else None
    return output


def _price(input_tokens, output_tokens, input_per_m, output_per_m):
    if input_tokens is None or output_tokens is None or input_per_m is None or output_per_m is None:
        return None
    # Use Decimal to avoid overstating cost precision.
    v=(Decimal(input_tokens)*Decimal(str(input_per_m)) + Decimal(output_tokens)*Decimal(str(output_per_m)))/Decimal(1000000)
    return str(v.quantize(Decimal('0.000001')))


def evaluate_model(run_model, limit=12, input_per_m=None, output_per_m=None, seed=None):
    """run_model(signals, label) -> (proposal, model_name, telemetry).

    Use only with explicit real endpoint, or mark fixture runner as MOCK in caller.
    """
    if type(limit) is not int or not 1<=limit<=len(CASES):
        raise ValueError('limit must be an integer in [1,12]')
    for price in (input_per_m,output_per_m):
        if price is not None and (not Decimal(str(price)).is_finite() or Decimal(str(price))<0):
            raise ValueError('price cannot be negative or non-finite')
    if (input_per_m is None)!=(output_per_m is None):
        raise ValueError('both model token prices must be specified together')
    if seed is None: seed=secrets.token_bytes(32)
    if not isinstance(seed,bytes) or len(seed)<16:raise ValueError('private blinding seed must be >=16 bytes')
    rows=[];blinded=[];key=[];model_names=set();token_costs=[]
    for case_id,signals,expected in CASES[:limit]:
        baseline=rule_output(signals)
        verdict=None;payload=None;failure=None
        from time import perf_counter
        started=perf_counter()
        try:
            candidate,model,telemetry=run_model(signals,'合成体育培训课程')
            model_names.add(str(model)[:100]);verdict=grade_output(candidate,signals)
            if verdict['accepted']:payload=verdict['result']
            else:failure='QUALITY_GATE_REJECTED: '+verdict['reason']
        except Exception as exc:
            telemetry={};failure='MODEL_CALL_FAILED: '+type(exc).__name__
        usage=_safe_usage(telemetry)
        if usage['latency_ms'] is None:usage['latency_ms']=round((perf_counter()-started)*1000,2)
        cost=_price(usage['prompt_tokens'],usage['completion_tokens'],input_per_m,output_per_m)
        if cost is not None:token_costs.append(Decimal(cost))
        row={'case_id':case_id,'expected_action':expected,'accepted':payload is not None,
             'reason':failure if failure else 'ACCEPTED',**usage,'estimated_api_cost':cost}
        rows.append(row)
        if payload is None:continue
        # Keep answer mapping separate from blinded reviewer sheet.
        model_first=(hmac.new(seed,case_id.encode(),hashlib.sha256).digest()[0]&1)==0
        def format_advice(item):
            return (f"行动：{item['action_code']}；依据：{', '.join(item['evidence_keys'])}；"
                    f"建议：{item['message']}；不确定性：{item['uncertainty']}")
        A,B=(payload,baseline) if model_first else (baseline,payload)
        blinded.append({'case_id':case_id,'variant_A':format_advice(A),'variant_B':format_advice(B),
                        **{f:'' for f in FIELDS if f not in ('case_id','variant_A','variant_B')}})
        key.append({'case_id':case_id,'model_variant':'A' if model_first else 'B',
                    'model_output_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                    'rule_output_sha256':hashlib.sha256(json.dumps(baseline,sort_keys=True,ensure_ascii=False).encode()).hexdigest()})
    success=sum(r['accepted'] for r in rows)
    elapsed=[r['latency_ms'] for r in rows if r['latency_ms'] is not None]
    known_usage=len(token_costs)==len(rows)
    report={'schema_version':SCHEMA_VERSION,'suite':SUITE,'suite_sha256':suite_digest(),
            'policy_version':POLICY_VERSION,'evaluation_kind':'LIVE_MODEL_MACHINE_CHECK',
            'run_at_utc':datetime.now(timezone.utc).isoformat(),'models':sorted(model_names),
            'cases_requested':limit,'cases_tested':len(rows),'machine_accepted':success,
            'machine_acceptance_rate':round(success/len(rows),4),
            'blind_review_pairs':len(blinded),'total_prompt_tokens':sum(r['prompt_tokens'] for r in rows) if all(r['prompt_tokens'] is not None for r in rows) else None,
            'total_completion_tokens':sum(r['completion_tokens'] for r in rows) if all(r['completion_tokens'] is not None for r in rows) else None,
            'average_latency_ms':round(sum(elapsed)/len(elapsed),2) if elapsed else None,
            'estimated_total_api_cost':str(sum(token_costs)) if known_usage else None,
            'cost_currency':'user_supplied_pricing_currency' if input_per_m is not None else None,
            'human_preference':None,'causal_revenue_uplift':None,'business_roi':None,
            'results':rows,'limitations':('Model success means machine policy compliance only. '
                         'Use at least two independent blinded reviewers to test preference. '
                         'No client transaction or business impact is measured.')}
    return report,blinded,{'schema_version':SCHEMA_VERSION,'suite_sha256':suite_digest(),
                            'seed_hex':seed.hex(),'mapping':key}


def reviewer_csv(rows):
    f=io.StringIO(newline='');w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator='\n');w.writeheader()
    for row in rows:w.writerow({key:row.get(key,'') for key in FIELDS})
    return f.getvalue()


def write_artifacts(directory,report,blind,key):
    p=Path(directory);p.mkdir(parents=True,exist_ok=True)
    if any((p/name).exists() for name in ('machine_report.json','blind_review_template.csv','private_answer_key.json')):
        raise FileExistsError('Refuse to overwrite an existing benchmark run; choose a fresh directory')
    (p/'machine_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (p/'blind_review_template.csv').write_text(reviewer_csv(blind),encoding='utf-8')
    private=p/'private_answer_key.json'
    private.write_text(json.dumps(key,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:private.chmod(0o600)
    except OSError:pass
    return [str(p/x) for x in ('machine_report.json','blind_review_template.csv','private_answer_key.json')]


def score_human_reviews(csv_texts,answer_key):
    """Score completed independent reviewer sheets. Never pool unreviewed cases."""
    mapping={x['case_id']:x['model_variant'] for x in answer_key['mapping']}
    by_case={case:[] for case in mapping}
    aliases=set()
    for text in csv_texts:
        reader=csv.DictReader(io.StringIO(text))
        if not set(FIELDS).issubset(reader.fieldnames or []):raise ValueError('review CSV schema mismatch')
        reviewer=None;seen=set()
        for row in reader:
            case=row['case_id'];alias=row['reviewer_alias'].strip()
            # Blank template rows may be omitted. A partially filled row is invalid.
            if not alias and not row['preferred_variant'].strip():continue
            if not alias or case not in mapping or case in seen:raise ValueError('unknown/duplicate case or reviewer')
            if reviewer is None:reviewer=alias
            if alias!=reviewer:raise ValueError('one reviewer identity per file')
            for key in ('A_grounded_1_5','B_grounded_1_5','A_actionable_1_5','B_actionable_1_5','A_respectful_1_5','B_respectful_1_5'):
                if row[key].strip() not in ('1','2','3','4','5'):raise ValueError('each dimension must be rated 1-5')
            if row['preferred_variant'] not in ('A','B','tie'):raise ValueError('preference must be A/B/tie')
            for key in ('safety_violation_A','safety_violation_B'):
                if row[key] not in ('yes','no'):raise ValueError('safety violation must be yes/no')
            if not row['reason'].strip():raise ValueError('reviewer rationale required')
            by_case[case].append({'reviewer':alias,'preference':row['preferred_variant'],
                                  'model_variant':mapping[case]})
            seen.add(case)
        if reviewer:
            if reviewer in aliases:raise ValueError('reviewer identities must be independent')
            aliases.add(reviewer)
    complete=(len(aliases)>=2 and all(len({entry['reviewer'] for entry in reviews})>=2 for reviews in by_case.values()))
    reviewed=[r for values in by_case.values() for r in values]
    model_wins=sum(x['preference']==x['model_variant'] for x in reviewed)
    rule_wins=sum(x['preference'] not in ('tie',x['model_variant']) for x in reviewed)
    return {'evaluation_kind':'BLINDED_HUMAN_PREFERENCE','complete':complete,
            'reviewers':len(aliases),'reviewed_ratings':len(reviewed),'expected_ratings':len(mapping)*2,
            'model_preferred':model_wins,'rule_preferred':rule_wins,
            'ties':sum(x['preference']=='tie' for x in reviewed),
            'observed_preference_only':bool(complete),
            'claim_model_advantage_allowed':False,
            'limitation':'Preference does not demonstrate improved renewal or ROI.'}
