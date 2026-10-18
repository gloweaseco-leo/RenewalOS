"""G0.8 manager read-only *process* evidence on synthetic/local data.

Metrics use one row per existing opportunity/source package. A cash fact is not
incremental revenue, an employee workload count is not employee performance,
and opportunity cohorts are NOT causal treatment-effect estimates.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from .db import connect

STAGE_LABELS = {
    'control': '对照组（仅正常运营）',
    'net_paid': '已产生关联净付款',
    'legacy_paid': '仅旧版净付款记录',
    'contract_no_net': '已签合同但无关联净付款',
    'followed': '已人工跟进未签约',
    'assigned': '已分配尚未跟进',
    'unassigned': '待分配',
}
OPEN = {'open', 'in_progress', 'waiting'}


def _day(raw):
    return datetime.fromisoformat(raw.replace('Z', '+00:00')).date() if raw else None


def manager_snapshot(store_id=None, path=None, today=None):
    """One point-in-time read, with explicit stage & cash definitions.

    Never infers attribution, uses mutually exclusive opportunity stages and
    separate non-sequential milestone counts. No mutation or side effects.
    """
    today = today or date.today()
    if store_id is not None and (len(store_id) > 100 or not store_id.strip()):
        raise ValueError('门店代号不合法')
    with connect(path) as con:
        # No joins to 1:N followups or cash_events: each source package counted once.
        sql = '''SELECT o.opportunity_id,o.package_id,o.priority,o.is_active,o.updated_at,
            l.store_id,l.guardian_alias, a.arm, p.course_type,
            t.task_id,t.owner,t.due_on,t.status AS task_status,t.updated_at AS task_updated_at,
            (SELECT COUNT(*) FROM followups f WHERE f.opportunity_id=o.opportunity_id) AS followup_count,
            (SELECT MAX(f.logged_at) FROM followups f WHERE f.opportunity_id=o.opportunity_id) AS last_followup_at,
            rc.contract_id,
            (SELECT COALESCE(SUM(CASE WHEN c.kind='payment' THEN c.amount_cents ELSE -c.amount_cents END),0)
                FROM cash_events c WHERE c.contract_id=rc.contract_id) AS net_cents,
            (SELECT COALESCE(SUM(CASE WHEN c.kind='payment' THEN c.amount_cents ELSE 0 END),0)
                FROM cash_events c WHERE c.contract_id=rc.contract_id) AS gross_cents,
            (SELECT COALESCE(SUM(CASE WHEN n.status='paid' THEN n.amount_cents
                                    WHEN n.status='refunded' THEN -n.amount_cents ELSE 0 END),0)
                FROM renewals n WHERE n.source_package_id=o.package_id) AS legacy_net_cents
            FROM opportunities o
            JOIN learners l ON l.learner_id=o.learner_id
            JOIN packages p ON p.package_id=o.package_id
            JOIN experiment_assignments a ON a.store_id=l.store_id AND a.family_id=l.family_id
            LEFT JOIN work_tasks t ON t.opportunity_id=o.opportunity_id
            LEFT JOIN renewal_contracts rc ON rc.source_package_id=o.package_id'''
        args = ()
        if store_id:
            sql += ' WHERE l.store_id=?'
            args = (store_id,)
        sql += ' ORDER BY o.priority DESC,o.opportunity_id'
        rows = con.execute(sql, args).fetchall()

    counts = Counter()
    milestones = Counter()
    owners = defaultdict(lambda: {'total':0,'open':0,'overdue':0,'resolved':0, 'cases_with_net_payment':0})
    alerts = []
    cases = []
    net_total = 0
    legacy_total = 0
    for r in rows:
        p = dict(r)
        linked = p['net_cents']
        legacy = p['legacy_net_cents']
        net_total += linked
        legacy_total += legacy
        for key, truth in [('assigned', bool(p['task_id'])), ('followed',p['followup_count']>0),
                            ('contracted',bool(p['contract_id'])), ('linked_net_paid',linked>0),
                            ('legacy_net_paid',legacy>0)]:
            if truth: milestones[key]+=1
        if p['arm']=='control':
            stage='control'
        elif linked>0:
            stage='net_paid'
        elif legacy>0:
            stage='legacy_paid'
        elif p['contract_id']:
            stage='contract_no_net'
        elif p['followup_count']:
            stage='followed'
        elif p['task_id']:
            stage='assigned'
        else:
            stage='unassigned'
        counts[stage]+=1
        if p['is_active']: milestones['active']+=1
        else: milestones['archived']+=1
        if p['arm']=='control': milestones['control']+=1
        if p['task_id']:
            owner=owners[p['owner']]
            owner['total']+=1
            if p['task_status'] in OPEN:
                owner['open']+=1
                if p['due_on']<today.isoformat():owner['overdue']+=1
            else:owner['resolved']+=1
            if linked>0:owner['cases_with_net_payment']+=1
        case = {'opportunity_id':p['opportunity_id'],'package_id':p['package_id'],
                'store_id':p['store_id'],'guardian_alias':p['guardian_alias'],
                'course_type':p['course_type'],'arm':p['arm'],
                'priority':p['priority'],'is_active':bool(p['is_active']),
                'stage':stage,'stage_label':STAGE_LABELS[stage],
                'task_id':p['task_id'],'owner':p['owner'],'task_status':p['task_status'],
                'followup_count':p['followup_count'],'contract_id':p['contract_id'],
                'net_paid_cny':round(linked/100,2),'legacy_net_cny':round(legacy/100,2)}
        cases.append(case)
        def flag(kind,label,urgency):
            alerts.append({'kind':kind,'label':label,'urgency':urgency,
                           'opportunity_id':p['opportunity_id'],'task_id':p['task_id'],
                           'store_id':p['store_id'],'owner':p['owner'], 'priority':p['priority']})
        # Do not issue targeted intervention alerts for normal-service control group.
        if p['arm']=='control':continue
        if p['task_id'] and p['task_status'] in OPEN and p['due_on']<today.isoformat() and p['is_active']:
            flag('overdue','已逾期，请核实任务处置',3)
        if p['task_id'] and p['task_status'] in OPEN and not p['is_active']:
            flag('archived_open_task','机会已归档，尚有未结束任务',3)
        if p['is_active'] and p['priority']>=65 and not p['task_id']:
            flag('high_priority_unassigned','高优先级机会尚未分配任务',2)
        if p['is_active'] and p['task_status']=='waiting' and _day(p['task_updated_at']):
            if (today-_day(p['task_updated_at'])).days>=3:
                flag('stale_waiting','等待状态超过3天，需人工复核',2)
        if p['contract_id'] and p['gross_cents']>0 and linked<=0:
            flag('net_zero_after_refund','关联款项净额为零，核查退款/后续服务',2)

    alerts.sort(key=lambda x:(-x['urgency'],-x['priority'],x['opportunity_id'],x['kind']))
    return {
        'scope':store_id or 'ALL_LOCAL_STORES','as_of':today.isoformat(),
        'summary':{
            'opportunities':len(rows),'active':milestones['active'],'archived':milestones['archived'],
            'active_non_control':sum(x['is_active'] and x['arm']!='control' for x in cases),
            'task_overdue':sum(v['overdue'] for v in owners.values()),
            'linked_net_cash_cny':round(net_total/100,2),
            'legacy_net_cash_cny':round(legacy_total/100,2),
            'roi':None,'incremental_profit_cny':None,'attribution_status':'NOT_ESTABLISHED'
        },
        'stage_counts':{k:counts[k] for k in STAGE_LABELS},
        'stage_labels':STAGE_LABELS,
        'milestones':{k:milestones[k] for k in ('assigned','followed','contracted','linked_net_paid','legacy_net_paid','control')},
        'owner_workload':[{'owner':name,**v} for name,v in sorted(owners.items())],
        'alerts':alerts[:50], 'alert_count':len(alerts),
        'cases':cases[:200], 'case_count':len(cases),
        'limitations':[
            '仅为本地合成业务数据；不代表真实运营结果。',
            '阶段为当前互斥状态；过程里程碑可能跨步骤，不可当成因果转化漏斗。',
            '关联现金与旧版续费记录分别展示，严禁相加以免重复计量。',
            '员工代号和工作量不是绩效排名；无登录身份或权限控制。',
            '未建立随机实验的成熟因果估计、完整贡献成本和ROI。'
        ]
    }
