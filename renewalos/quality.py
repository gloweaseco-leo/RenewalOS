"""G0.4 evidence-first action policy and bounded model validation.

This module does not pretend to predict churn or calculate incremental ROI.
An accepted model answer is a reviewable draft, not an approved outreach.
"""
import hashlib
import json
import re
from dataclasses import dataclass

POLICY_VERSION = 'g04.1'
ACTION_LABELS = {
    'attendance_service_check': '先核实缺课原因及服务体验',
    'post_expiry_service': '先核实过期权益和服务安排',
    'course_progress_review': '先由教练评估学习进度',
    'routine_expiry_notice': '正常到期服务提醒',
}
EVIDENCE_KEYS = {
    'days_to_expiry', 'remaining_sessions', 'attendance_previous_28d',
    'attendance_recent_28d', 'near_expiry', 'few_sessions', 'attendance_drop',
}
FORBIDDEN = [
    r'(?:已经|确定|肯定|就是|必然)(?:因为|由于).{0,14}(?:价格|收入|疾病|健康|家庭|不满)',
    r'(?:打[一二三四五六七八九\d]+折|免费赠送|保证续费|保证成交|优惠券|承诺返现)',
    r'(?:立即|直接|自动)(?:群发|发送|联系|扣款)',
]

class AdviceRejected(ValueError):
    """A suggested action is not sufficiently grounded for presentation."""


def canonical_signals(raw):
    if not isinstance(raw, dict):
        raise AdviceRejected('信号结构必须是对象')
    if set(raw) != EVIDENCE_KEYS:
        raise AdviceRejected('信号字段不完整或含非许可数据')
    values = {}
    for key in ('days_to_expiry', 'remaining_sessions', 'attendance_previous_28d', 'attendance_recent_28d'):
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 10000:
            raise AdviceRejected(f'信号字段 {key} 类型或范围不符合要求')
        if key != 'days_to_expiry' and value < 0:
            raise AdviceRejected('课时及出勤不能为负数')
        values[key] = value
    for key in ('near_expiry', 'few_sessions', 'attendance_drop'):
        if type(raw[key]) is not bool:
            raise AdviceRejected(f'布尔信号 {key} 不合法')
        values[key] = raw[key]
    return values


def signal_fingerprint(signals, course_type):
    clean = canonical_signals(signals)
    # Hash only minimized business facts, not customer names or IDs.
    payload = json.dumps({'policy': POLICY_VERSION, 'signals': clean, 'course_type': course_type},
                         sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def expected_action(signals):
    s = canonical_signals(signals)
    if s['attendance_drop']:
        return 'attendance_service_check', ('attendance_previous_28d', 'attendance_recent_28d')
    if s['days_to_expiry'] < 0:
        return 'post_expiry_service', ('days_to_expiry',)
    if s['few_sessions']:
        return 'course_progress_review', ('remaining_sessions',)
    return 'routine_expiry_notice', ('days_to_expiry',)


def rule_output(signals):
    action, evidence = expected_action(signals)
    messages = {
        'attendance_service_check': '观察到近期到课下降。请人工核实缺课原因及服务体验，未经确认不推断家长意愿。',
        'post_expiry_service': '课包已过期。请人工核对权益与课程安排，并确认是否需要正常续课服务。',
        'course_progress_review': '剩余课时偏少。请教练先评估进度与课程适配，再询问续课意愿。',
        'routine_expiry_notice': '课包临近到期。按正常服务流程确认后续课程计划，不作无依据的流失判断。',
    }
    return dict(action_code=action, evidence_keys=list(evidence), message=messages[action],
                uncertainty='客户续费意愿和具体原因尚未确认，必须由员工核实。')


def validate_model_advice(payload, signals):
    s = canonical_signals(signals)
    if not isinstance(payload, dict) or set(payload) != {'action_code','evidence_keys','message','uncertainty'}:
        raise AdviceRejected('模型必须返回 action_code、evidence_keys、message、uncertainty 四个字段')
    expected, required = expected_action(s)
    action = payload['action_code']
    if action not in ACTION_LABELS or action != expected:
        raise AdviceRejected('模型建议不符合证据约束的安全行动顺序')
    keys = payload['evidence_keys']
    if not isinstance(keys, list) or not keys or any(not isinstance(k, str) for k in keys):
        raise AdviceRejected('证据字段必须是非空字符串数组')
    if len(keys) != len(set(keys)) or any(k not in EVIDENCE_KEYS for k in keys):
        raise AdviceRejected('模型引用了不存在或重复的证据字段')
    if not set(required).issubset(keys):
        raise AdviceRejected('缺少关键决策依据')
    message = payload['message']
    uncertainty = payload['uncertainty']
    if not isinstance(message, str) or not isinstance(uncertainty, str):
        raise AdviceRejected('建议和不确定性必须是文本')
    if not 12 <= len(message.strip()) <= 160 or not 8 <= len(uncertainty.strip()) <= 130:
        raise AdviceRejected('建议或不确定性文本长度不合规')
    if not any(word in uncertainty for word in ('人工', '确认', '核实', '未知', '不能确定', '不确定')):
        raise AdviceRejected('必须说明仍有待人工核实的事实')
    combined = message + uncertainty
    if any(re.search(pattern, combined) for pattern in FORBIDDEN):
        raise AdviceRejected('包含无证据的原因推断、未授权营销承诺或自动执行请求')
    if re.search(r'\b(?:\+?86[ -]?)?1[3-9]\d{9}\b', combined):
        raise AdviceRejected('输出不得出现电话号码')
    return {'action_code': action, 'evidence_keys': keys,
            'message': message.strip(), 'uncertainty': uncertainty.strip()}


def grade_output(payload, signals):
    try:
        normalized = validate_model_advice(payload, signals)
        return {'accepted': True, 'action_correct': True, 'evidence_sufficient': True,
                'reason': '通过机器可验证的证据与安全门槛', 'result': normalized}
    except AdviceRejected as exc:
        # A failed guardrail is not automatically a factual hallucination rate.
        return {'accepted': False, 'action_correct': False, 'evidence_sufficient': False,
                'reason': str(exc), 'result': None}
