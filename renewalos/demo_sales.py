"""G0.6: auditable *synthetic-only* sales walkthrough.

All public endpoints using these helpers are localhost-only and explicitly marked
as simulated entries. This is NOT a payment gateway or proof of a real receipt.
Reuses the existing immutable contract/cash fact primitives.
"""
from datetime import date
from .db import connect
from .facts import BusinessRuleError, import_cash_events, import_contracts


def assert_not_future(day: date):
    if day > date.today():
        raise BusinessRuleError('模拟操作日期不能晚于今天')


def record_contract(package_id, contract_id, day, amount_cents, path=None):
    assert_not_future(day)
    with connect(path) as con:
        package = con.execute('SELECT learner_id FROM packages WHERE package_id=?', (package_id,)).fetchone()
        if not package:
            raise BusinessRuleError('来源课包不存在')
        learner_id = package['learner_id']
    import_contracts([(contract_id, learner_id, package_id, day.isoformat(), amount_cents)], path=path)
    return sales_summary(package_id, path)


def record_payment(contract_id, event_id, day, amount_cents, path=None):
    assert_not_future(day)
    # G0.6 manual entry prevents synthetic overcollection, whereas CSV imports
    # remain source-of-truth events and may expose discrepancies separately.
    with connect(path) as con:
        contract = con.execute('SELECT source_package_id,contracted_amount_cents FROM renewal_contracts WHERE contract_id=?', (contract_id,)).fetchone()
        if not contract:
            raise BusinessRuleError('新续费合同不存在')
        old = con.execute('SELECT contract_id,kind,amount_cents,event_on,refund_of FROM cash_events WHERE event_id=?', (event_id,)).fetchone()
        if old:
            if (old['contract_id'],old['kind'],old['amount_cents'],old['event_on'],old['refund_of']) != (contract_id,'payment',amount_cents,day.isoformat(),None):
                raise BusinessRuleError('付款事件编号冲突，不得覆盖')
            return sales_summary(contract['source_package_id'], path)
        gross = con.execute("SELECT COALESCE(SUM(amount_cents),0) FROM cash_events WHERE contract_id=? AND kind='payment'",(contract_id,)).fetchone()[0]
        if gross + amount_cents > contract['contracted_amount_cents']:
            raise BusinessRuleError('模拟收款累计不得超过合同约定金额')
        source_package_id = contract['source_package_id']
    import_cash_events([(event_id, contract_id, day.isoformat(), 'payment', amount_cents, None)], path=path)
    return sales_summary(source_package_id, path)


def record_refund(payment_id, event_id, day, amount_cents, path=None):
    assert_not_future(day)
    with connect(path) as con:
        payment = con.execute('''SELECT rc.source_package_id, p.contract_id FROM cash_events p
                                 JOIN renewal_contracts rc ON rc.contract_id=p.contract_id
                                 WHERE p.event_id=? AND p.kind='payment' ''',(payment_id,)).fetchone()
        if not payment:
            raise BusinessRuleError('原付款事件不存在')
        contract_id = payment['contract_id']
        source_package_id = payment['source_package_id']
    import_cash_events([(event_id,contract_id,day.isoformat(),'refund',amount_cents,payment_id)], path=path)
    return sales_summary(source_package_id, path)


def sales_summary(package_id, path=None):
    with connect(path) as con:
        pkg = con.execute('SELECT package_id,learner_id FROM packages WHERE package_id=?',(package_id,)).fetchone()
        if not pkg:
            raise BusinessRuleError('来源课包不存在')
        contract = con.execute('SELECT * FROM renewal_contracts WHERE source_package_id=?',(package_id,)).fetchone()
        if not contract:
            return {'package_id':package_id,'contract':None,'payments':[], 'net_paid_cny':0.0,
                    'status':'not_signed','disclaimer':'仅本机合成业务演示；不是实际支付凭证或AI带来的增量收入。'}
        rows = con.execute('''SELECT e.event_id,e.event_on,e.kind,e.amount_cents,e.refund_of
                              FROM cash_events e WHERE contract_id=?
                              ORDER BY e.event_on,e.event_id''',(contract['contract_id'],)).fetchall()
        all_refunds={}
        for e in rows:
            if e['kind']=='refund':
                all_refunds[e['refund_of']]=all_refunds.get(e['refund_of'],0)+e['amount_cents']
        events = []
        net = 0
        for e in rows:
            net += e['amount_cents'] if e['kind']=='payment' else -e['amount_cents']
            events.append({'event_id':e['event_id'],'event_on':e['event_on'], 'kind':e['kind'],
                           'amount_cny':round(e['amount_cents']/100,2),'refund_of':e['refund_of'],
                           'refundable_cny':round(max(0,e['amount_cents']-all_refunds.get(e['event_id'],0))/100,2) if e['kind']=='payment' else None})
        return {'package_id':package_id,'contract':{'contract_id':contract['contract_id'],
                   'signed_on':contract['signed_on'],'amount_cny':round(contract['contracted_amount_cents']/100,2)},
                'payments':events,'net_paid_cny':round(net/100,2),
                'status':'net_paid' if net>0 else 'no_net_payment',
                'disclaimer':'模拟交易事实，非第三方支付核验；成交不等于AI创造的增量。'}
