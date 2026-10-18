"""Frozen synthetic fixture suite; machine checks are not human quality ratings."""
from .quality import rule_output, grade_output, POLICY_VERSION


def _s(days, remaining, prior, recent, near=False, few=False, down=False):
    return dict(days_to_expiry=days, remaining_sessions=remaining,
                attendance_previous_28d=prior, attendance_recent_28d=recent,
                near_expiry=near, few_sessions=few, attendance_drop=down)

# Only invented numeric conditions; no minors' names, phone numbers, family notes.
CASES = (
    ('attendance_first', _s(18, 2, 8, 1, True, True, True), 'attendance_service_check'),
    ('attendance_midcycle', _s(70, 8, 6, 0, False, False, True), 'attendance_service_check'),
    ('expiry_negative', _s(-3, 6, 2, 2, True, False, False), 'post_expiry_service'),
    ('expired_few', _s(-6, 1, 0, 0, True, True, False), 'post_expiry_service'),
    ('few_sessions', _s(65, 2, 4, 4, False, True, False), 'course_progress_review'),
    ('expiry_few', _s(7, 3, 6, 6, True, True, False), 'course_progress_review'),
    ('expiry_only', _s(25, 7, 3, 3, True, False, False), 'routine_expiry_notice'),
    ('expiry_today', _s(0, 7, 2, 2, True, False, False), 'routine_expiry_notice'),
    ('no_fabrication', _s(10, 0, 4, 1, True, True, True), 'attendance_service_check'),
    ('sparse_attendance', _s(22, 9, 0, 0, True, False, False), 'routine_expiry_notice'),
    ('older_package', _s(85, 2, 0, 0, False, True, False), 'course_progress_review'),
    ('post_expiry_drop', _s(-1, 4, 8, 1, True, True, True), 'attendance_service_check'),
)


def baseline_report():
    results=[]
    for case_id,signals,expected in CASES:
        result=grade_output(rule_output(signals),signals)
        results.append({'case_id':case_id,'expected_action':expected,
                        'action_code':rule_output(signals)['action_code'],
                        'accepted':result['accepted'], 'reason':result['reason']})
    return {'suite':'g04-fixed-synthetic-v1','policy_version':POLICY_VERSION,
            'evaluation_kind':'DETERMINISTIC_RULE_BASELINE', 'cases':len(CASES),
            'machine_passed':sum(x['accepted'] for x in results), 'results':results,
            'human_quality_rating':None, 'model_incremental_value':None,
            'disclaimer':'合成样本仅验证机器门槛，不证明AI优于规则、续费提升或财务ROI。'}


def benchmark_model(run_model, limit=4):
    """Explicit user-triggered live cost; serial calls, small hard cap."""
    limit=max(1,min(int(limit),4))
    results=[]
    for case_id,signals,expected in CASES[:limit]:
        try:
            payload,model=run_model(signals,'合成体育培训课程')
            verdict=grade_output(payload,signals)
            results.append({'case_id':case_id,'expected_action':expected,
                            'accepted':verdict['accepted'],'reason':verdict['reason']})
        except Exception as exc:
            results.append({'case_id':case_id,'expected_action':expected,
                            'accepted':False,'reason':f'调用失败：{type(exc).__name__}'})
    return {'suite':'g04-fixed-synthetic-v1','policy_version':POLICY_VERSION,
            'evaluation_kind':'REAL_MODEL_MACHINE_CHECK', 'cases':len(results),
            'machine_passed':sum(x['accepted'] for x in results),'results':results,
            'human_quality_rating':None,'model_incremental_value':None,
            'disclaimer':'实测仅衡量结构化输出与安全证据合规；未评估客户接受度、人工质量或经营增量。'}