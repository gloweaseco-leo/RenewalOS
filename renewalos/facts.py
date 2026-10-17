"""G0.3: immutable enrollment snapshots and auditable contract/cash facts.

Local demonstration only. Neither a payment processor nor an accounting ledger.
"""
from datetime import date, timedelta
from .db import connect
from .core import assign_arm, now_iso

WINDOW_DAYS = 45
REFUND_GRACE_DAYS = 14


class BusinessRuleError(ValueError):
    pass


def freeze_cohort(store_id: str, path=None, today=None):
    """Freeze forward-looking eligible families, exactly once per store/day.

    Requires current date: importing today's snapshot cannot reconstruct a historical
    population without time-versioned consent and entitlement information.
    """
    day = today or date.today()
    if day != date.today():
        raise BusinessRuleError('禁止回溯冻结：缺少历史权益和联系授权快照')
    if not store_id or len(store_id) > 100 or ':' in store_id:
        raise BusinessRuleError('门店标识无效')
    cohort_id = f'{store_id}::{day.isoformat()}'
    with connect(path) as con:
        found = con.execute('SELECT cohort_id FROM cohorts WHERE cohort_id=?', (cohort_id,)).fetchone()
        if found:
            return cohort_summary(cohort_id, path=path, con=con)
        con.execute('INSERT INTO cohorts(cohort_id,store_id,opened_on,cutoff_on,refund_grace_until,frozen_at) VALUES(?,?,?,?,?,?)',
                    (cohort_id, store_id, day.isoformat(), (day+timedelta(days=WINDOW_DAYS)).isoformat(),
                     (day+timedelta(days=WINDOW_DAYS+REFUND_GRACE_DAYS)).isoformat(), now_iso()))
        candidates = con.execute('''SELECT p.package_id,p.learner_id,p.expires_on,l.family_id
               FROM packages p JOIN learners l ON p.learner_id=l.learner_id
               WHERE l.store_id=? AND l.contact_consent=1 AND p.purchased_on <= ?
                 AND p.expires_on BETWEEN ? AND ?
               ORDER BY p.package_id''',
               (store_id, day.isoformat(), day.isoformat(), (day+timedelta(days=30)).isoformat())).fetchall()
        for p in candidates:
            old = con.execute('''SELECT 1 FROM renewal_cohort_members WHERE source_package_id=?''',
                              (p['package_id'],)).fetchone()
            if old:
                continue
            # Only future renewals count after freeze. Pre-existing paid cases are not eligible.
            legacy = con.execute('''SELECT COALESCE(SUM(CASE WHEN status='paid' THEN amount_cents
                                        WHEN status='refunded' THEN -amount_cents ELSE 0 END),0) AS net
                          FROM renewals WHERE source_package_id=? AND paid_on<=?''',
                          (p['package_id'], day.isoformat())).fetchone()['net']
            linked = con.execute('''SELECT COALESCE(SUM(CASE WHEN e.kind='payment' THEN e.amount_cents
                                      WHEN e.kind='refund' THEN -e.amount_cents ELSE 0 END),0) AS net
                          FROM renewal_contracts rc JOIN cash_events e ON rc.contract_id=e.contract_id
                          WHERE rc.source_package_id=? AND e.event_on<=?''',
                          (p['package_id'],day.isoformat())).fetchone()['net']
            if legacy > 0 or linked > 0:
                continue
            family_key = f'{store_id}:{p["family_id"]}'
            con.execute('''INSERT OR IGNORE INTO experiment_assignments
                   (family_key,store_id,family_id,arm,assigned_on) VALUES(?,?,?,?,?)''',
                   (family_key,store_id,p['family_id'],assign_arm(family_key),day.isoformat()))
            arm = con.execute('SELECT arm FROM experiment_assignments WHERE family_key=?',
                              (family_key,)).fetchone()['arm']
            con.execute('''INSERT INTO renewal_cohort_members
                  (cohort_id,source_package_id,learner_id,family_key,arm,expiry_at_freeze)
                  VALUES(?,?,?,?,?,?)''',
                  (cohort_id,p['package_id'],p['learner_id'],family_key,arm,p['expires_on']))
        return cohort_summary(cohort_id,path=path,con=con)


def import_contracts(rows, path=None):
    """Never mutate accepted economic facts; identical retries are safe."""
    with connect(path) as con:
        for record in rows:
            cid, lid, pkgid, signed, value = record
            pkg=con.execute('SELECT p.learner_id,p.purchased_on FROM packages p WHERE p.package_id=?', (pkgid,)).fetchone()
            if not pkg or pkg['learner_id']!=lid:
                raise BusinessRuleError('新续费合同与来源课包学员归属不一致')
            if signed < pkg['purchased_on']:
                raise BusinessRuleError('续费签署日不能早于原课包购买日')
            exists=con.execute('SELECT * FROM renewal_contracts WHERE contract_id=? OR source_package_id=?',
                               (cid,pkgid)).fetchone()
            if exists:
                values=(exists['contract_id'],exists['learner_id'],exists['source_package_id'],
                        exists['signed_on'],exists['contracted_amount_cents'])
                if values!=record:
                    raise BusinessRuleError('合同ID或来源课包已关联不同合同，不能覆盖历史事实')
                continue
            con.execute('''INSERT INTO renewal_contracts
                (contract_id,learner_id,source_package_id,signed_on,contracted_amount_cents)
                VALUES(?,?,?,?,?)''',record)
    return len(rows)


def import_cash_events(rows,path=None):
    """Contract-linked payment/refund events, with chronological nonnegative balance.

    All records are append-only. A conflicting retry or an over-refund fails the
    entire batch; already-stored records are never rewritten or silently deleted.
    """
    with connect(path) as con:
        for record in rows:
            event_id,cid,when,kind,amount,refund_of=record
            contract=con.execute('SELECT signed_on FROM renewal_contracts WHERE contract_id=?',(cid,)).fetchone()
            if not contract:
                raise BusinessRuleError('找不到对应续费合同')
            if when < contract['signed_on']:
                raise BusinessRuleError('付款或退款不得早于合同签署日')
            old=con.execute('SELECT * FROM cash_events WHERE event_id=?',(event_id,)).fetchone()
            if old:
                existing=(old['event_id'],old['contract_id'],old['event_on'],old['kind'],old['amount_cents'],old['refund_of'])
                if existing!=record:
                    raise BusinessRuleError('交易事件ID冲突，已记账事件不可覆盖')
                continue
            if kind=='payment' and refund_of:
                raise BusinessRuleError('付款事件不得关联被退款交易')
            if kind=='refund':
                payment=con.execute('SELECT contract_id,event_on,kind FROM cash_events WHERE event_id=?',(refund_of,)).fetchone()
                if not payment or payment['kind']!='payment' or payment['contract_id']!=cid:
                    raise BusinessRuleError('退款必须绑定同一合同的真实付款事件')
                if when < payment['event_on']:
                    raise BusinessRuleError('退款不得早于原付款')
            con.execute('''INSERT INTO cash_events(event_id,contract_id,event_on,kind,amount_cents,refund_of)
                           VALUES(?,?,?,?,?,?)''',record)
        payments={r['refund_of'] for r in con.execute("SELECT refund_of FROM cash_events WHERE kind='refund'")}
        for payment_id in payments:
            paid=con.execute('SELECT amount_cents FROM cash_events WHERE event_id=?',(payment_id,)).fetchone()
            returned=con.execute('SELECT SUM(amount_cents) FROM cash_events WHERE refund_of=?',(payment_id,)).fetchone()[0]
            if not paid or returned > paid['amount_cents']:
                raise BusinessRuleError('单笔付款的累计退款不能超过付款金额')
    return len(rows)


def cohort_summary(cohort_id, path=None, con=None, as_of=None):
    if con is None:
        with connect(path) as owned:
            return cohort_summary(cohort_id,con=owned,as_of=as_of)
    today=as_of or date.today()
    cohort=con.execute('SELECT * FROM cohorts WHERE cohort_id=?',(cohort_id,)).fetchone()
    if not cohort:
        raise BusinessRuleError('不存在该冻结队列')
    groups={a:{'member_packages':0,'families':set(),'paid_families':set(),
               'gross_paid_cents':0,'refund_cents':0,'net_paid_cents':0} for a in ('control','rules','ai')}
    members=con.execute('''SELECT m.*,rc.contract_id
                           FROM renewal_cohort_members m LEFT JOIN renewal_contracts rc
                            ON rc.source_package_id=m.source_package_id WHERE m.cohort_id=?''',(cohort_id,)).fetchall()
    for m in members:
        arm=m['arm']; group=groups[arm]
        group['member_packages']+=1
        group['families'].add(m['family_key'])
        if not m['contract_id']:
            continue
        paid=con.execute('''SELECT event_id,amount_cents FROM cash_events
                           WHERE contract_id=? AND kind='payment' AND event_on BETWEEN ? AND ? AND event_on<=?''',
                         (m['contract_id'],cohort['opened_on'],cohort['cutoff_on'],today.isoformat())).fetchall()
        counted_ids=[e['event_id'] for e in paid]
        gross=sum(e['amount_cents'] for e in paid)
        refund=0
        for payment_id in counted_ids:
            refund+=con.execute('''SELECT COALESCE(SUM(amount_cents),0) FROM cash_events
                          WHERE refund_of=? AND kind='refund' AND event_on<=?''',
                          (payment_id,today.isoformat())).fetchone()[0]
        group['gross_paid_cents']+=gross
        group['refund_cents']+=refund
        group['net_paid_cents']+=gross-refund
        if gross-refund>0:
            group['paid_families'].add(m['family_key'])
    compact={arm:{'member_packages':g['member_packages'],'eligible_families':len(g['families']),
                  'paid_families':len(g['paid_families']),
                  'gross_paid_cny':round(g['gross_paid_cents']/100,2),
                  'refund_cny':round(g['refund_cents']/100,2),
                  'net_paid_cny':round(g['net_paid_cents']/100,2)} for arm,g in groups.items()}
    mature=today.isoformat()>=cohort['refund_grace_until']
    return dict(cohort_id=cohort_id,store_id=cohort['store_id'],opened_on=cohort['opened_on'],
                cutoff_on=cohort['cutoff_on'],refund_grace_until=cohort['refund_grace_until'],
                mature=mature,arms=compact,incremental_profit_cny=None,roi=None,
                attribution_status='DESCRIPTIVE_ONLY' if mature else 'OBSERVATION_PENDING',
                attribution_note='合同与流水仅提供队列内的描述性事实。未评估基线平衡、统计区间和贡献成本，不宣称AI增量ROI。')


def list_cohorts(path=None):
    with connect(path) as con:
        rows=con.execute('SELECT cohort_id FROM cohorts ORDER BY opened_on DESC,cohort_id').fetchall()
    return [cohort_summary(r['cohort_id'],path=path) for r in rows]


def cycle_timeline(package_id,path=None):
    with connect(path) as con:
        pkg=con.execute('SELECT * FROM packages WHERE package_id=?',(package_id,)).fetchone()
        if not pkg:
            raise BusinessRuleError('原课包不存在')
        events=[dict(event_type='package',event_at=pkg['purchased_on'],reference_id=package_id,
                     amount_cny=round(pkg['price_cents']/100,2))]
        member=con.execute('''SELECT c.opened_on,m.cohort_id,m.arm FROM renewal_cohort_members m
                              JOIN cohorts c ON c.cohort_id=m.cohort_id WHERE m.source_package_id=?''',(package_id,)).fetchone()
        if member:
            events.append(dict(event_type='cohort_freeze',event_at=member['opened_on'],
                               reference_id=member['cohort_id'],arm=member['arm']))
        opportunity=con.execute('SELECT opportunity_id,updated_at,closed_at FROM opportunities WHERE package_id=?',(package_id,)).fetchone()
        if opportunity:
            for e in con.execute('SELECT followup_id,logged_at,status FROM followups WHERE opportunity_id=?',(opportunity['opportunity_id'],)):
                events.append(dict(event_type='followup',event_at=e['logged_at'],reference_id=e['followup_id'],status=e['status']))
        contract=con.execute('SELECT * FROM renewal_contracts WHERE source_package_id=?',(package_id,)).fetchone()
        if contract:
            events.append(dict(event_type='renewal_contract',event_at=contract['signed_on'],reference_id=contract['contract_id'],
                               contracted_amount_cny=round(contract['contracted_amount_cents']/100,2)))
            for e in con.execute('SELECT * FROM cash_events WHERE contract_id=? ORDER BY event_on,event_id',(contract['contract_id'],)):
                events.append(dict(event_type=e['kind'],event_at=e['event_on'],reference_id=e['event_id'],
                                   amount_cny=round(e['amount_cents']/100,2)))
        for r in con.execute('SELECT * FROM renewals WHERE source_package_id=? ORDER BY paid_on,renewal_id',(package_id,)):
            events.append(dict(event_type='legacy_'+r['status'],event_at=r['paid_on'],reference_id=r['renewal_id'],
                               amount_cny=round(r['amount_cents']/100,2)))
        events.sort(key=lambda e:(e['event_at'],e['event_type'],str(e['reference_id'])))
        return dict(source_package_id=package_id,learner_id=pkg['learner_id'],events=events,
                    disclaimer='历史旧续费行没有独立合同标识，与新流水不合并作为同一笔收入。')