"""Explainable rules and durable business-event history, not a churn predictor."""
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from .db import connect

ARMS = ('control', 'rules', 'ai')

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def assign_arm(family_key: str) -> str:
    salt = os.getenv('RENEWAL_EXPERIMENT_SALT', 'demo-salt-not-for-production')
    digest = hashlib.sha256((salt + ':' + family_key).encode()).digest()
    return ARMS[int.from_bytes(digest[:8], 'big') % len(ARMS)]

def attendance_counts(rows, reference_day):
    recent_start = reference_day - timedelta(days=27)
    prior_start = reference_day - timedelta(days=55)
    recent = sum(1 for r in rows if r['status'] == 'present' and recent_start <= date.fromisoformat(r['session_date']) <= reference_day)
    prior = sum(1 for r in rows if r['status'] == 'present' and prior_start <= date.fromisoformat(r['session_date']) < recent_start)
    return prior, recent

def derive_opportunity(package, learner, att_rows, today):
    if not learner['contact_consent']:
        return None
    expiry = date.fromisoformat(package['expires_on'])
    days = (expiry - today).days
    remaining = package['remaining_sessions']
    near_expiry = -7 <= days <= 30
    few_sessions = remaining <= 4 and -7 <= days <= 90
    prior, recent = attendance_counts(att_rows, today)
    down = -7 <= days <= 90 and prior >= 2 and recent < prior * .5
    if not (near_expiry or few_sessions or down):
        return None
    signals = dict(days_to_expiry=days, remaining_sessions=remaining,
                   attendance_previous_28d=prior, attendance_recent_28d=recent,
                   near_expiry=near_expiry, few_sessions=few_sessions,
                   attendance_drop=down)
    priority = (35 if near_expiry else 0) + (30 if few_sessions else 0) + (25 if down else 0)
    if days < 0:
        priority += 10
    reasons = []
    if near_expiry:
        reasons.append(f'距到期{days}天' if days >= 0 else f'已过期{-days}天')
    if few_sessions:
        reasons.append(f'剩余{remaining}节')
    if down:
        reasons.append(f'出勤从{prior}次降至{recent}次')
    if down:
        advice = '请先了解近期到课减少的原因和服务体验；未经确认不要假设是价格问题或直接促销。'
    elif days < 0:
        advice = '请核查权益和服务安排，确认是否仍有续课需求；先提供服务说明，不自动承诺补偿。'
    elif few_sessions:
        advice = '请教练评估学习进度和后续课程匹配度，再由员工询问续课意愿。'
    else:
        advice = '按正常服务节奏提醒课程即将到期，确认后续学习计划，不做无依据的流失判断。'
    return dict(opportunity_id='O-' + package['package_id'], learner_id=package['learner_id'],
                package_id=package['package_id'], priority=min(priority, 100),
                signals_json=json.dumps(signals, ensure_ascii=False),
                reason='；'.join(reasons), rule_advice=advice, updated_at=now_iso())

def recompute(path=None, today=None):
    today = today or date.today()
    with connect(path) as con:
        learners = {r['learner_id']: r for r in con.execute('SELECT * FROM learners')}
        attendance = {}
        for r in con.execute('SELECT * FROM attendance'):
            attendance.setdefault(r['learner_id'], []).append(r)
        paid = {r['source_package_id'] for r in con.execute('''
           SELECT source_package_id FROM renewals GROUP BY source_package_id
           HAVING SUM(CASE WHEN status='paid' THEN amount_cents
                           WHEN status='refunded' THEN -amount_cents ELSE 0 END)>0''')}
        accepted = []
        for pkg in con.execute('SELECT * FROM packages'):
            if pkg['package_id'] in paid:
                continue
            learner = learners.get(pkg['learner_id'])
            if learner is None:
                continue
            opportunity = derive_opportunity(pkg, learner, attendance.get(pkg['learner_id'], []), today)
            if opportunity:
                accepted.append((opportunity, learner))
        active = {o['opportunity_id'] for o, _ in accepted}
        # Preserve opportunity records AND followup history for audit. Never rewrite the past.
        for row in con.execute('SELECT opportunity_id FROM opportunities WHERE is_active=1').fetchall():
            if row['opportunity_id'] not in active:
                con.execute('UPDATE opportunities SET is_active=0, closed_at=? WHERE opportunity_id=?',
                            (now_iso(), row['opportunity_id']))
        for opportunity, learner in accepted:
            prev = con.execute('SELECT signals_json FROM opportunities WHERE opportunity_id=?',
                               (opportunity['opportunity_id'],)).fetchone()
            if prev and prev['signals_json'] != opportunity['signals_json']:
                con.execute('DELETE FROM ai_advice WHERE opportunity_id=?', (opportunity['opportunity_id'],))
            # A household key is scoped to the store to prevent cross-store contamination.
            family_key = f"{learner['store_id']}:{learner['family_id']}"
            con.execute('''INSERT OR IGNORE INTO experiment_assignments
                (family_key,store_id,family_id,arm,assigned_on) VALUES (?,?,?,?,?)''',
                (family_key, learner['store_id'], learner['family_id'], assign_arm(family_key), today.isoformat()))
            con.execute('''INSERT INTO opportunities
                (opportunity_id,learner_id,package_id,signals_json,priority,reason,rule_advice,updated_at,is_active,closed_at)
                VALUES (:opportunity_id,:learner_id,:package_id,:signals_json,:priority,:reason,:rule_advice,:updated_at,1,NULL)
                ON CONFLICT(opportunity_id) DO UPDATE SET signals_json=excluded.signals_json,
                priority=excluded.priority, reason=excluded.reason,rule_advice=excluded.rule_advice,
                updated_at=excluded.updated_at,is_active=1,closed_at=NULL''', opportunity)
    return len(accepted)

def list_opportunities(path=None, include_archived=False):
    with connect(path) as con:
        q = '''SELECT o.*, l.family_id,l.guardian_alias,l.store_id,p.course_type,p.expires_on,
               a.arm,aa.advice AS model_advice,aa.source AS model_source,
               (SELECT status FROM followups f WHERE f.opportunity_id=o.opportunity_id ORDER BY followup_id DESC LIMIT 1) AS last_status,
               (SELECT owner FROM followups f WHERE f.opportunity_id=o.opportunity_id ORDER BY followup_id DESC LIMIT 1) AS last_owner
               FROM opportunities o JOIN learners l ON o.learner_id=l.learner_id
               JOIN packages p ON o.package_id=p.package_id
               JOIN experiment_assignments a ON l.family_id=a.family_id AND l.store_id=a.store_id
               LEFT JOIN ai_advice aa ON o.opportunity_id=aa.opportunity_id
               WHERE (?=1 OR o.is_active=1)
               ORDER BY o.is_active DESC,o.priority DESC,o.opportunity_id'''
        result = []
        for row in con.execute(q, (int(include_archived),)):
            item = dict(row)
            item['signals'] = json.loads(item.pop('signals_json'))
            # Experiment protection: no extra outreach advice is exposed to control operators.
            if item['arm'] == 'control':
                item['rule_advice'] = None
                item['model_advice'] = None
                item['model_source'] = None
            result.append(item)
        return result

def list_followups(path=None, opportunity_id=None):
    with connect(path) as con:
        if opportunity_id is None:
            return [dict(r) for r in con.execute('SELECT * FROM followups ORDER BY followup_id DESC')]
        return [dict(r) for r in con.execute('SELECT * FROM followups WHERE opportunity_id=? ORDER BY followup_id DESC', (opportunity_id,))]

def report(path=None, today=None):
    today = today or date.today()
    with connect(path) as con:
        assignments = con.execute('SELECT arm, COUNT(*) n FROM experiment_assignments GROUP BY arm').fetchall()
        opportunities = con.execute('SELECT COUNT(*) FROM opportunities WHERE is_active=1').fetchone()[0]
        archived = con.execute('SELECT COUNT(*) FROM opportunities WHERE is_active=0').fetchone()[0]
        followups = con.execute('SELECT COUNT(*) FROM followups').fetchone()[0]
        paid = con.execute("SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM renewals WHERE status='paid'").fetchone()
        refunds = con.execute("SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM renewals WHERE status='refunded'").fetchone()
        arms = {r['arm']: r['n'] for r in assignments}
    # NOT a causal estimate. A frozen eligibility cohort, fixed outcome window,
    # sufficient sample and actual variable costs are required before net lift/ROI.
    return dict(opportunities=opportunities, archived_opportunities=archived,
                followup_records=followups, arm_family_counts={a: arms.get(a, 0) for a in ARMS},
                paid_record_count=paid[0], refunded_record_count=refunds[0],
                net_paid_cny=round((paid[1]-refunds[1])/100, 2),
                incremental_renewals=None, incremental_profit_cny=None, roi=None,
                attribution_status='NOT_ESTABLISHED',
                attribution_note='仅展示净交易事实。缺少冻结的合格客户队列、成熟观察期及可验证成本；不得把自然续费认作AI增量。',
                as_of=today.isoformat())