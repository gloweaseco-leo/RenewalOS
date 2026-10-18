"""RenewalOS local demo API. Never expose on the public internet."""
import csv
import io
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel,Field
from .db import connect,initialize
from .core import recompute, list_opportunities, list_followups, report, now_iso
from .demo import load_demo
from .ai import suggest,suggest_with_telemetry,AIUnavailable
from .quality import validate_model_advice,signal_fingerprint,AdviceRejected,POLICY_VERSION
from .evaluation import baseline_report,benchmark_model
from .benchmark_lab import evaluate_model
from .facts import (freeze_cohort,list_cohorts,cycle_timeline,import_contracts,
                    import_cash_events,BusinessRuleError)
from .demo_sales import record_contract, record_payment, record_refund, sales_summary

ROOT=Path(__file__).resolve().parent.parent
SCHEMAS={
 "learners":{"learner_id","family_id","guardian_alias","store_id","contact_consent"},
 "packages":{"package_id","learner_id","course_type","purchased_on","expires_on","purchased_sessions","remaining_sessions","price_cny"},
 "attendance":{"event_id","learner_id","session_date","status"},
 "renewals":{"renewal_id","learner_id","source_package_id","paid_on","amount_cny","status"},
 "contracts":{"contract_id","learner_id","source_package_id","signed_on","contracted_amount_cny"},
 "cash_events":{"event_id","contract_id","event_on","kind","amount_cny","refund_of"}
}

def cents(value):
    try:
        decimal=Decimal(value)
        if not decimal.is_finite() or decimal < 0 or decimal.as_tuple().exponent < -2:
            raise ValueError("金额必须为非负且最多两位小数")
        return int(decimal*100)
    except (InvalidOperation,ValueError) as e:
        raise ValueError("金额格式错误或小数位过多") from e

def str_date(value):
    return date.fromisoformat(value).isoformat()

def convert(kind,r):
    if kind=="learners":
        if r["contact_consent"].lower() not in ("yes","no"):
            raise ValueError("contact_consent 只允许 yes/no")
        if ':' in r['family_id'] or ':' in r['store_id']:raise ValueError('家庭/门店ID不得包含冒号')
        return (r["learner_id"],r["family_id"],r["guardian_alias"],r["store_id"],int(r["contact_consent"].lower()=="yes"))
    if kind=="packages":
        purchased=str_date(r["purchased_on"]); expires=str_date(r["expires_on"])
        if expires < purchased:raise ValueError("到期日不可早于购买日")
        count=int(r["purchased_sessions"]); remains=int(r["remaining_sessions"])
        if count<=0 or remains<0 or remains>count:raise ValueError("课时数据不合理")
        return (r["package_id"],r["learner_id"],r["course_type"],purchased,expires,count,remains,cents(r["price_cny"]))
    if kind=="attendance":
        if r["status"] not in ("present","absent","excused"):raise ValueError("考勤状态不支持")
        return (r["event_id"],r["learner_id"],str_date(r["session_date"]),r["status"])
    if kind=="renewals":
        if r["status"] not in ("paid","refunded","void"):raise ValueError("交易状态不支持")
        return (r["renewal_id"],r["learner_id"],r["source_package_id"],str_date(r["paid_on"]),cents(r["amount_cny"]),r["status"])
    if kind=="contracts":
        return (r["contract_id"],r["learner_id"],r["source_package_id"],str_date(r["signed_on"]),cents(r["contracted_amount_cny"]))
    if kind=="cash_events":
        if r["kind"] not in ("payment","refund"):raise ValueError("交易类型只能为 payment/refund")
        refund_of=r["refund_of"] or None
        if (r["kind"]=="refund")!=bool(refund_of):raise ValueError("退款必须填写原付款ID，付款不得填写")
        value=cents(r["amount_cny"])
        if value==0:raise ValueError("交易金额必须大于零")
        return (r["event_id"],r["contract_id"],str_date(r["event_on"]),r["kind"],value,refund_of)
    raise ValueError("未知数据类型")

@asynccontextmanager
async def lifespan(app):
    initialize()
    yield

app=FastAPI(title="RenewalOS Demo",version="0.6.0",lifespan=lifespan,
    docs_url=None,redoc_url=None,openapi_url=None)

@app.middleware("http")
async def demo_local_only(request:Request, call_next):
    # Secure default: only trusted local host values and same-origin writes.
    # This is a local demonstration, NOT multiuser authentication.
    host=request.url.hostname
    if host not in {"localhost","127.0.0.1","[::1]","::1","testserver"}:
        return JSONResponse({"detail":"仅允许本机访问"},status_code=403)
    if request.method not in {"GET","HEAD","OPTIONS"}:
        origin=request.headers.get("origin")
        if origin:
            from urllib.parse import urlparse
            parsed=urlparse(origin)
            if parsed.hostname not in {"localhost","127.0.0.1","::1"} or parsed.scheme not in {"http","https"}:
                return JSONResponse({"detail":"禁止跨站写入"},status_code=403)
    return await call_next(request)

# G0.6: Synthetic sales events; these are NOT production payment endpoints.
# Client-generated event IDs permit safe retries without duplicate transactions.
class DemoContract(BaseModel):
    source_package_id: str=Field(min_length=2,max_length=120,pattern=r'^[A-Za-z0-9_-]+$')
    contract_id: str=Field(min_length=2,max_length=120,pattern=r'^[A-Za-z0-9_-]+$')
    signed_on: date
    amount_cny: Decimal=Field(gt=0,le=1000000,decimal_places=2)

class DemoPayment(BaseModel):
    contract_id: str=Field(min_length=2,max_length=120,pattern=r'^[A-Za-z0-9_-]+$')
    event_id: str=Field(min_length=2,max_length=120,pattern=r'^[A-Za-z0-9_-]+$')
    event_on: date
    amount_cny: Decimal=Field(gt=0,le=1000000,decimal_places=2)

class DemoRefund(BaseModel):
    payment_event_id: str=Field(min_length=2,max_length=120,pattern=r'^[A-Za-z0-9_-]+$')
    event_id: str=Field(min_length=2,max_length=120,pattern=r'^[A-Za-z0-9_-]+$')
    event_on: date
    amount_cny: Decimal=Field(gt=0,le=1000000,decimal_places=2)

class FreezeRequest(BaseModel):
    store_id: str=Field(min_length=1,max_length=100)

class ReviewRequest(BaseModel):
    reviewer: str=Field(min_length=1,max_length=50)
    decision: str

class BenchmarkRequest(BaseModel):
    max_cases: int=Field(default=4,ge=1,le=4)

class Followup(BaseModel):
    opportunity_id:str=Field(min_length=2,max_length=120)
    owner:str=Field(min_length=1,max_length=50)
    status:str
    note:str=Field(max_length=1000,default="")

@app.get("/")
def home():return FileResponse(ROOT/"static"/"index.html")
@app.get("/static/style.css")
def style():return FileResponse(ROOT/"static"/"style.css",media_type="text/css")
@app.get("/static/app.js")
def script():return FileResponse(ROOT/"static"/"app.js",media_type="application/javascript")
@app.get("/api/health")
def health():
    return {"ok":True,"mode":"LOCAL_DEMO","ai_configured":all((os.getenv("RENEWAL_AI_BASE_URL"),os.getenv("RENEWAL_AI_API_KEY"),os.getenv("RENEWAL_AI_MODEL")))}
@app.post("/api/demo/reset")
def reset():return {"opportunities":load_demo(),"mode":"SYNTHETIC_DEMO"}
@app.post("/api/recompute")
def refresh():return {"opportunities":recompute()}
@app.get("/api/opportunities")
def opportunities(include_archived: bool=False):
    return {"items":list_opportunities(include_archived=include_archived)}
@app.get("/api/followups/{opportunity_id}")
def followup_history(opportunity_id: str):
    return {"items": list_followups(opportunity_id=opportunity_id)}

@app.get("/api/report")
def metrics():return report()

@app.post("/api/cohorts/freeze")
def freeze(data:FreezeRequest):
    try:return freeze_cohort(data.store_id)
    except BusinessRuleError as e:raise HTTPException(422,str(e)) from e

@app.get("/api/cohorts")
def cohorts():return {"items":list_cohorts()}

@app.get("/api/cycles/{package_id}/timeline")
def timeline(package_id:str):
    try:return cycle_timeline(package_id)
    except BusinessRuleError as e:raise HTTPException(404,str(e)) from e

@app.get('/api/demo/sales/{package_id}')
def demo_sale_info(package_id: str):
    try:return sales_summary(package_id)
    except BusinessRuleError as e:raise HTTPException(404,str(e)) from e

@app.post('/api/demo/sales/contracts')
def demo_contract(data:DemoContract):
    try:
        return record_contract(data.source_package_id,data.contract_id,data.signed_on,cents(str(data.amount_cny)))
    except BusinessRuleError as e:raise HTTPException(422,str(e)) from e

@app.post('/api/demo/sales/payments')
def demo_payment(data:DemoPayment):
    try:
        result=record_payment(data.contract_id,data.event_id,data.event_on,cents(str(data.amount_cny)))
        recompute()
        return result
    except BusinessRuleError as e:raise HTTPException(422,str(e)) from e

@app.post('/api/demo/sales/refunds')
def demo_refund(data:DemoRefund):
    try:
        result=record_refund(data.payment_event_id,data.event_id,data.event_on,cents(str(data.amount_cny)))
        recompute()
        return result
    except BusinessRuleError as e:raise HTTPException(422,str(e)) from e

@app.post("/api/import/{kind}")
async def import_csv(kind:str,request:Request):
    if kind not in SCHEMAS:raise HTTPException(404,"不支持此类型")
    raw=await request.body()
    if not raw or len(raw)>2*1024*1024:raise HTTPException(413,"CSV不得为空，且最大2MB")
    try:
        decoded=raw.decode("utf-8-sig")
        if "\x00" in decoded:raise ValueError("二进制数据不支持")
        rdr=csv.DictReader(io.StringIO(decoded))
        if not rdr.fieldnames or set(rdr.fieldnames)!=SCHEMAS[kind]:
            raise ValueError(f"CSV表头不匹配，必须为: {', '.join(sorted(SCHEMAS[kind]))}")
        items=[]
        for row_num,r in enumerate(rdr,start=2):
            if row_num>5001:raise ValueError("单次最多5000条")
            if None in r or any(v is None or len(v)>256 for v in r.values()):
                raise ValueError(f"第{row_num}行有缺项或字段过长")
            vals=convert(kind,{k:v.strip() for k,v in r.items()})
            if not all(v is not None and v!="" for v in vals if kind!="cash_events"):
                raise ValueError(f"第{row_num}行包含空值")
            if kind=="cash_events" and not all(v is not None and v!="" for v in vals[:5]):
                raise ValueError(f"第{row_num}行包含空值")
            items.append(vals)
        if not items: raise ValueError("CSV无数据行")
        if kind=="contracts":
            return {"kind":kind,"imported":import_contracts(items),"message":"合同事实已导入（重传相同行幂等；冲突不可覆盖）。"}
        if kind=="cash_events":
            return {"kind":kind,"imported":import_cash_events(items),"message":"真实付款/退款事件已关联合同；退款必须指向原付款。"}
        columns={
          "learners":"learner_id,family_id,guardian_alias,store_id,contact_consent",
          "packages":"package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cents",
          "attendance":"event_id,learner_id,session_date,status",
          "renewals":"renewal_id,learner_id,source_package_id,paid_on,amount_cents,status"}[kind]
        marks=",".join("?" for _ in items[0])
        pk={"learners":"learner_id","packages":"package_id","attendance":"event_id","renewals":"renewal_id"}[kind]
        rest=[c for c in columns.split(",") if c!=pk]
        q=f"INSERT INTO {kind}({columns}) VALUES({marks}) ON CONFLICT({pk}) DO UPDATE SET "+",".join(f"{c}=excluded.{c}" for c in rest)
        with connect() as con:
            if kind == "learners":
                for value in items:
                    existing=con.execute("SELECT * FROM learners WHERE learner_id=?",(value[0],)).fetchone()
                    if existing and (existing['store_id']!=value[3] or existing['family_id']!=value[1]):
                        raise ValueError("已有学员的家庭或门店归属不可变更，请先核实源数据")
            if kind == "renewals":
                for value in items:
                    package = con.execute("SELECT learner_id FROM packages WHERE package_id=?", (value[2],)).fetchone()
                    if package is None or package["learner_id"] != value[1]:
                        raise ValueError("续费记录与课包所属学员不一致，拒绝导入")
            if kind == "packages":
                for value in items:
                    existing = con.execute("SELECT learner_id FROM packages WHERE package_id=?", (value[0],)).fetchone()
                    if existing and existing["learner_id"] != value[1]:
                        raise ValueError("已有课包不允许变更学员归属")
                    frozen=con.execute("SELECT 1 FROM renewal_cohort_members WHERE source_package_id=?",(value[0],)).fetchone()
                    if frozen:
                        original=con.execute("SELECT * FROM packages WHERE package_id=?",(value[0],)).fetchone()
                        # Only freeze immutable baseline facts; remaining sessions can evolve during service.
                        if (original['learner_id'],original['purchased_on'],original['expires_on'],original['purchased_sessions'],original['price_cents']) != (value[1],value[3],value[4],value[5],value[7]):
                            raise ValueError("已冻结队列的课包基线不得改写")
            con.executemany(q,items)
        # We intentionally do not re-compute automatically after every import;
        # importing dimensions across CSVs may have partial referential coverage.
        return {"kind":kind,"imported":len(items),"message":"已写入；导入完全部文件后点击重新计算。"}
    except (ValueError,UnicodeError,sqlite3.IntegrityError,OverflowError) as e:
        raise HTTPException(422,str(e)) from e

@app.post("/api/followups")
def save_followup(data:Followup):
    if data.status not in ("planned","contacted","no_response","not_suitable","closed"):
        raise HTTPException(422,"无效状态")
    with connect() as con:
        existing=con.execute("""SELECT a.arm FROM opportunities o JOIN learners l ON l.learner_id=o.learner_id
                       JOIN experiment_assignments a ON l.family_id=a.family_id AND l.store_id=a.store_id WHERE o.opportunity_id=? AND o.is_active=1""",(data.opportunity_id,)).fetchone()
        if not existing:raise HTTPException(404,"机会不存在")
        if existing["arm"]=="control":raise HTTPException(403,"对照组不接受额外定向跟进；保持正常既有服务。")
        con.execute("INSERT INTO followups(opportunity_id,owner,status,note,logged_at) VALUES(?,?,?,?,?)",
                    (data.opportunity_id,data.owner,data.status,data.note,now_iso()))
    return {"ok":True}

@app.get('/api/quality/baseline')
def quality_baseline():
    return baseline_report()

@app.post('/api/quality/benchmark')
def quality_benchmark(request:BenchmarkRequest):
    if not all((os.getenv('RENEWAL_AI_BASE_URL'),os.getenv('RENEWAL_AI_API_KEY'),os.getenv('RENEWAL_AI_MODEL'))):
        raise HTTPException(409,'未配置真实模型，不能运行真实模型评测。')
    # Explicit, small-batch, synthetic-only, real provider costs may apply.
    # This UI action is explicitly confirmed by the operator and bounded to 4 calls.
    # Return telemetry only; the private blind-review key is never exposed via API.
    report, _, _ = evaluate_model(suggest_with_telemetry, request.max_cases)
    return {**report, 'cases':report['cases_tested'],
            'machine_passed':report['machine_accepted'],
            'human_quality_rating':None,'model_incremental_value':None}

@app.post('/api/opportunities/{opportunity_id}/ai-advice')
def make_ai_advice(opportunity_id:str):
    with connect() as con:
        row=con.execute('''SELECT o.signals_json,p.course_type,a.arm FROM opportunities o
         JOIN packages p ON p.package_id=o.package_id JOIN learners l ON o.learner_id=l.learner_id
         JOIN experiment_assignments a ON a.family_id=l.family_id AND a.store_id=l.store_id
         WHERE o.opportunity_id=? AND o.is_active=1''',(opportunity_id,)).fetchone()
        if not row:raise HTTPException(404,'机会不存在')
        if row['arm']!='ai':raise HTTPException(403,'只有AI实验组可申请建议，防止串组。')
        signals=json.loads(row['signals_json'])
        course_type=row['course_type']
    fingerprint=signal_fingerprint(signals,course_type)
    model=os.getenv('RENEWAL_AI_MODEL','')[:100]
    try:
        raw,source=suggest(signals,course_type)
        result=validate_model_advice(raw,signals)
    except (AIUnavailable,AdviceRejected) as e:
        # Record failure without retaining unsafe raw model output.
        with connect() as con:
            con.execute('''INSERT INTO ai_advice_attempts
             (opportunity_id,signal_hash,model_name,status,rejection_reason,attempted_at)
             VALUES(?,?,?,?,?,?)''', (opportunity_id,fingerprint,model,'rejected',str(e)[:350],now_iso()))
        raise HTTPException(409,'AI建议被拒绝：'+str(e)) from e
    stale = False
    with connect() as con:
        latest=con.execute('''SELECT o.signals_json,p.course_type,o.is_active FROM opportunities o
             JOIN packages p ON p.package_id=o.package_id WHERE o.opportunity_id=?''',(opportunity_id,)).fetchone()
        if not latest or not latest['is_active'] or fingerprint != signal_fingerprint(json.loads(latest['signals_json']),latest['course_type']):
            con.execute('''INSERT INTO ai_advice_attempts
             (opportunity_id,signal_hash,model_name,status,rejection_reason,attempted_at)
             VALUES(?,?,?,?,?,?)''',(opportunity_id,fingerprint,source,'stale','模型调用期间经营事实已变化',now_iso()))
            stale=True
        else:
            con.execute('''INSERT INTO ai_advice
            (opportunity_id,advice,source,created_at,signal_hash,action_code,evidence_keys_json,
             uncertainty,review_status,policy_version)
            VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET
            advice=excluded.advice,source=excluded.source,created_at=excluded.created_at,
            signal_hash=excluded.signal_hash,action_code=excluded.action_code,
            evidence_keys_json=excluded.evidence_keys_json,uncertainty=excluded.uncertainty,
            review_status='pending_review',policy_version=excluded.policy_version''',
            (opportunity_id,result['message'],source,now_iso(),fingerprint,result['action_code'],
             json.dumps(result['evidence_keys'],ensure_ascii=False),result['uncertainty'],
             'pending_review',POLICY_VERSION))
            con.execute('''INSERT INTO ai_advice_attempts
             (opportunity_id,signal_hash,model_name,status,rejection_reason,attempted_at)
             VALUES(?,?,?,?,?,?)''',(opportunity_id,fingerprint,source,'accepted',None,now_iso()))
    if stale:
        raise HTTPException(409,'模型调用期间事实发生变化，旧建议已作废。')
    return {'advice':result['message'],'source':source,'action_code':result['action_code'],
            'evidence_keys':result['evidence_keys'],'uncertainty':result['uncertainty'],
            'review_status':'pending_review','quality_policy':POLICY_VERSION}

@app.post('/api/opportunities/{opportunity_id}/ai-review')
def review_ai_advice(opportunity_id:str,review:ReviewRequest):
    if review.decision not in ('approved','rejected'):
        raise HTTPException(422,'审核决定仅允许 approved/rejected')
    with connect() as con:
        row=con.execute('''SELECT o.is_active,o.signals_json,p.course_type,aa.signal_hash,
          aa.policy_version,a.arm FROM opportunities o JOIN packages p ON p.package_id=o.package_id
          JOIN learners l ON l.learner_id=o.learner_id
          JOIN experiment_assignments a ON a.store_id=l.store_id AND a.family_id=l.family_id
          JOIN ai_advice aa ON aa.opportunity_id=o.opportunity_id WHERE o.opportunity_id=?''',
          (opportunity_id,)).fetchone()
        if not row or row['arm']!='ai':raise HTTPException(404,'不存在可审核的AI组建议')
        if not row['is_active'] or row['policy_version']!=POLICY_VERSION or row['signal_hash'] != signal_fingerprint(json.loads(row['signals_json']),row['course_type']):
            raise HTTPException(409,'建议已过期或旧策略生成，不允许审核')
        con.execute('UPDATE ai_advice SET review_status=? WHERE opportunity_id=?',
                    (review.decision,opportunity_id))
        con.execute('''INSERT INTO ai_advice_reviews
          (opportunity_id,signal_hash,reviewer,decision,reviewed_at) VALUES (?,?,?,?,?)''',
          (opportunity_id,row['signal_hash'],review.reviewer,review.decision,now_iso()))
    return {'ok':True,'review_status':review.decision}
