"""G0.5 evaluation: stubs are NOT counted as real provider results."""
import csv
import io
import json
from pathlib import Path
import pytest
from renewalos.ai import suggest_with_telemetry
from renewalos.benchmark_lab import (
    evaluate_model,write_artifacts,score_human_reviews,reviewer_csv,suite_digest,SUITE)
from renewalos.evaluation import CASES
from renewalos.quality import rule_output
from renewalos.benchmark_cli import main as cli_main


def mock_provider(signals, course):
    return rule_output(signals), 'SIMULATED_NOT_REAL_MODEL', {'latency_ms':42, 'prompt_tokens':200, 'completion_tokens':50}


def test_suite_immutable_digest_and_machine_approval():
    report, blind, key=evaluate_model(mock_provider, limit=12,seed=b'0'*32,
        input_per_m='1.5',output_per_m='6')
    assert report['suite']==SUITE and report['suite_sha256']==suite_digest()
    assert report['cases_tested']==12 and report['machine_accepted']==12
    assert report['blind_review_pairs']==12 and report['human_preference'] is None
    assert report['business_roi'] is None and report['causal_revenue_uplift'] is None
    assert report['total_prompt_tokens']==2400 and report['total_completion_tokens']==600
    assert report['estimated_total_api_cost']=='0.007200'
    assert key['seed_hex']==(b'0'*32).hex()
    assert all(r['model_variant'] in ('A','B') for r in key['mapping'])
    assert all(row['reviewer_alias']=='' for row in blind)
    assert 'SIMULATED' in report['models'][0]


def test_invalid_rejected_proposals_cannot_be_exported():
    def ungrounded(s,c):
        return {'action_code':'send_discount','message':'绝对续费'},'TEST_STUB',{'prompt_tokens':None,'completion_tokens':None}
    report,blind,key=evaluate_model(ungrounded,limit=2,seed=b'1'*32)
    assert report['machine_accepted']==0 and report['blind_review_pairs']==0 and not blind
    assert report['estimated_total_api_cost'] is None
    assert '绝对续费' not in json.dumps(report,ensure_ascii=False)
    assert not key['mapping']


def test_error_cases_disclose_no_secrets_and_still_have_latency():
    def fail(s,c):raise ValueError('private invalid provider response')
    report,blind,key=evaluate_model(fail,limit=1,seed=b'1'*32)
    assert report['machine_accepted']==0
    assert report['results'][0]['reason']=='MODEL_CALL_FAILED: ValueError'
    assert report['results'][0]['latency_ms']>=0
    assert 'private invalid' not in json.dumps(report)


@pytest.mark.parametrize('bad', [0,13,True,1.3])
def test_benchmark_limit_bounded(bad):
    with pytest.raises(ValueError):evaluate_model(mock_provider,limit=bad)


def test_price_must_be_explicit_valid_pair():
    for prices in [(None,'1'),('-1','1'),('1','nan')]:
        with pytest.raises(ValueError):evaluate_model(mock_provider,limit=1,input_per_m=prices[0],output_per_m=prices[1])


def test_artifact_write_is_non_overwriting(tmp_path):
    result,blind,key=evaluate_model(mock_provider,limit=2,seed=b'2'*32)
    folder=tmp_path/'run-1';artifacts=write_artifacts(folder,result,blind,key)
    assert len(artifacts)==3
    assert json.loads((folder/'machine_report.json').read_text())['human_preference'] is None
    assert 'case_id,variant_A,variant_B' in (folder/'blind_review_template.csv').read_text()
    with pytest.raises(FileExistsError):write_artifacts(folder,result,blind,key)


def reviewed_csv(rows, reviewer, prefer_model, key):
    mapping={r['case_id']:r['model_variant'] for r in key['mapping']}
    revised=[]
    for row in rows:
        x=dict(row);x['reviewer_alias']=reviewer;x['preferred_variant']=mapping[row['case_id']] if prefer_model else ('B' if mapping[row['case_id']]=='A' else 'A')
        for k in ('A_grounded_1_5','B_grounded_1_5','A_actionable_1_5','B_actionable_1_5','A_respectful_1_5','B_respectful_1_5'):x[k]='5'
        x['safety_violation_A']='no';x['safety_violation_B']='no';x['reason']='Synthetic reviewer input for automated test only.'
        revised.append(x)
    return reviewer_csv(revised)


def test_blinded_reviews_need_two_independent_complete_raters():
    report,blind,key=evaluate_model(mock_provider,limit=2,seed=b'3'*32)
    first=reviewed_csv(blind,'QA-1',True,key)
    second=reviewed_csv(blind,'QA-2',False,key)
    partial=score_human_reviews([first],key)
    assert not partial['complete'] and not partial['claim_model_advantage_allowed']
    score=score_human_reviews([first,second],key)
    assert score['complete'] and score['model_preferred']==2 and score['rule_preferred']==2
    assert not score['claim_model_advantage_allowed']
    with pytest.raises(ValueError):score_human_reviews([first,first],key)


def test_cli_offline_is_not_live(tmp_path,monkeypatch):
    for key in ('RENEWAL_AI_BASE_URL','RENEWAL_AI_API_KEY','RENEWAL_AI_MODEL'):monkeypatch.delenv(key,raising=False)
    dest=tmp_path/'offline';assert cli_main(['--offline','--output-dir',str(dest)])==0
    baseline=json.loads((dest/'rule_baseline.json').read_text())
    assert baseline['evaluation_kind']=='DETERMINISTIC_RULE_BASELINE'
    with pytest.raises(SystemExit) as e:cli_main(['--output-dir',str(tmp_path/'live')])
    assert e.value.code==2
    with pytest.raises(SystemExit) as e:cli_main(['--acknowledge-live-cost','--output-dir',str(tmp_path/'live')])
    assert e.value.code==2


def test_instrumented_adapter_provider_usage_is_measured(monkeypatch):
    import renewalos.ai as ai
    monkeypatch.setenv('RENEWAL_AI_BASE_URL','https://example.org/v1')
    monkeypatch.setenv('RENEWAL_AI_API_KEY','test-not-a-real-secret')
    monkeypatch.setenv('RENEWAL_AI_MODEL','SIMULATED_PROVIDER')
    s=CASES[0][1];sent={}
    class MockResponse:
        headers={'Content-Length':'500'}
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,*a):
            return json.dumps({'choices':[{'message':{'content':json.dumps(rule_output(s),ensure_ascii=False)}}],
                               'usage':{'prompt_tokens':180,'completion_tokens':45}},ensure_ascii=False).encode()
    def fake_open(req,timeout):
        sent['body']=json.loads(req.data);return MockResponse()
    monkeypatch.setattr(ai.urllib.request,'urlopen',fake_open)
    result,model,tel=suggest_with_telemetry(s,'张三 13600000000')
    assert model=='SIMULATED_PROVIDER' and tel['prompt_tokens']==180 and tel['completion_tokens']==45
    assert tel['latency_ms']>=0 and result['action_code']=='attendance_service_check'
    assert '张三' not in json.dumps(sent,ensure_ascii=False) and '13600000000' not in json.dumps(sent)


def test_benchmark_api_absent_model_reports_no_live_calls(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from renewalos.main import app
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'local.db'))
    for x in ('RENEWAL_AI_BASE_URL','RENEWAL_AI_API_KEY','RENEWAL_AI_MODEL'):monkeypatch.delenv(x,raising=False)
    with TestClient(app) as c:
        assert c.post('/api/quality/benchmark',json={'max_cases':4}).status_code==409
        assert c.get('/api/quality/baseline').json()['machine_passed']==12
