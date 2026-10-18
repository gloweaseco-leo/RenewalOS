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
from .tasks import create_task,list_tasks,task_summary,task_history,update_task,record_task_followup,TaskRuleError,FOLLOWUP_TO_TASK,OPEN
from .ai import suggest,suggest_with_telemetry,AIUnavailable
from .quality import validate_model_advice,signal_fingerprint,AdviceRejected,POLICY_VERSION
from .evaluation import baseline_report,benchmark_model
from .benchmark_lab import evaluate_model
from .facts import (freeze_cohort,list_cohorts,cycle_timeline,import_contracts,
                    import_cash_events,BusinessRuleError)
from .demo_sales import record_contract, record_payment, record_refund, sales_summary
from .management import manager_snapshot
from .release_gate import assert_local_only,assert_dedicated_pg_roles,local_readiness
from .access import (initialize_access, login as access_login, logout as access_logout,
                     identity as access_identity, authorize_store, scoped_tasks,
                     scoped_opportunities, AccessDenied)

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

def _pg_auth_active():
    backend=os.getenv('RENEWAL_AUTH_BACKEND','sqlite')
    if backend not in ('sqlite','postgres','oidc'):
        raise RuntimeError('未知身份后端，拒绝启动')
    return backend in ('postgres','oidc')


@asynccontextmanager
async def lifespan(app):
    assert_local_only()
    mode=os.getenv('RENEWAL_RUNTIME_MODE','demo')
    if mode not in ('demo','secure_local'):
        raise RuntimeError('不支持的运行模式；拒绝在未知配置下启动')
    if mode=='secure_local' and _pg_auth_active():
        auth_dsn=os.getenv('RENEWAL_PG_AUTH_DSN','')
        app_dsn=os.getenv('RENEWAL_PG_APP_DSN','')
        if not auth_dsn or not app_dsn or auth_dsn==app_dsn:
            raise RuntimeError('PostgreSQL identity and business must use distinct configured roles')
        assert_dedicated_pg_roles()
        if os.getenv('RENEWAL_AUTH_BACKEND')=='oidc':
            from .oidc import OIDCConfig
            OIDCConfig.from_env()  # fail closed before serving any request
        # G1-E: never create or read a SQLite identity/business DB in PG mode.
    else:
        initialize()
        if mode == 'secure_local': initialize_access()
    yield

app=FastAPI(title="RenewalOS",version="1.0.0-beta3",lifespan=lifespan,
    docs_url=None,redoc_url=None,openapi_url=None)

@app.middleware("http")
async def demo_local_only(request:Request, call_next):
    # Secure default: only trusted local host values and same-origin writes.
    # This is a local demonstration, NOT multiuser authentication.
    host=request.url.hostname
    peer=request.client.host if request.client else None
    if (host not in {"localhost","127.0.0.1","[::1]","::1","testserver"} or
            peer not in {'127.0.0.1','::1','testclient'}):
        # This is defense-in-depth ONLY. A reverse proxy on loopback may still
        # forward internet traffic, so bind the server to 127.0.0.1 as well.
        return JSONResponse({"detail":"仅允许本机访问"},status_code=403)
    if request.method not in {"GET","HEAD","OPTIONS"}:
        origin=request.headers.get("origin")
        if origin:
            from urllib.parse import urlparse
            parsed=urlparse(origin)
            if parsed.hostname not in {"localhost","127.0.0.1","::1"} or parsed.scheme not in {"http","https"}:
                return JSONResponse({"detail":"禁止跨站写入"},status_code=403)
    if os.getenv('RENEWAL_RUNTIME_MODE', 'demo') == 'secure_local':
        # Fail closed: legacy demo business APIs are unauthenticated and must not be
        # exposed even when a valid session token is present.
        allowed=(request.url.path in ('/api/health','/api/ready') or
                 request.url.path in ('/','/static/secure.css','/static/secure.js',
                                      '/api/auth/login','/api/auth/logout',
                                      '/api/auth/methods','/api/auth/oidc/start',
                                      '/api/auth/oidc/complete') or
                 request.url.path.startswith('/api/v1/'))
        if not allowed:
            return JSONResponse({'detail':'安全模式已禁用旧演示功能，请使用受保护接口'},status_code=403)
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

class TaskCreate(BaseModel):
    opportunity_id: str=Field(min_length=2,max_length=120)
    owner: str=Field(min_length=1,max_length=50)
    due_on: date
    note: str=Field(default='',max_length=1000)

class TaskUpdate(BaseModel):
    actor: str=Field(min_length=1,max_length=50)
    owner: str|None=Field(default=None,max_length=50)
    due_on: date|None=None
    status: str|None=None
    note: str=Field(default='',max_length=1000)

class TaskFollowup(BaseModel):
    actor: str=Field(min_length=1,max_length=50)
    status: str
    note: str=Field(default='',max_length=1000)

class Followup(BaseModel):
    opportunity_id:str=Field(min_length=2,max_length=120)
    owner:str=Field(min_length=1,max_length=50)
    status:str
    note:str=Field(max_length=1000,default="")

@app.get("/")
def home():
    if os.getenv("RENEWAL_RUNTIME_MODE", "demo")=="secure_local":
        return FileResponse(ROOT/"static"/"secure.html")
    return FileResponse(ROOT/"static"/"index.html")
@app.get("/static/secure.css")
def secure_css():return FileResponse(ROOT/"static"/"secure.css",media_type="text/css")
@app.get("/static/secure.js")
def secure_js():return FileResponse(ROOT/"static"/"secure.js",media_type="application/javascript")
@app.get("/static/style.css")
def style():return FileResponse(ROOT/"static"/"style.css",media_type="text/css")
@app.get("/static/app.js")
def script():return FileResponse(ROOT/"static"/"app.js",media_type="application/javascript")

# G1-A: these APIs are the ONLY business endpoints available in secure_local mode.
# All store scopes are derived from authenticated membership, never trusted from
# client-supplied aliases. Public/hosted execution remains forbidden.
class LocalCredentials(BaseModel):
    username: str=Field(min_length=2,max_length=64)
    password: str=Field(min_length=1,max_length=256)


def _require_secure():
    if os.getenv('RENEWAL_RUNTIME_MODE', 'demo') != 'secure_local':
        raise HTTPException(404, '接口不存在')


def _bearer(request:Request):
    raw=request.headers.get('authorization','')
    parts=raw.split()
    if len(parts)!=2 or parts[0].lower()!='bearer':
        raise HTTPException(status_code=401,detail='未认证',headers={'WWW-Authenticate':'Bearer'})
    return parts[1]


@app.post('/api/auth/login')
def local_login(credentials:LocalCredentials):
    _require_secure()
    if os.getenv('RENEWAL_AUTH_BACKEND')=='oidc':
        raise HTTPException(403,'OIDC模式已禁用本地密码登录')
    try:
        if _pg_auth_active():
            from .pg_auth import login
            return login(os.environ['RENEWAL_PG_AUTH_DSN'],credentials.username,credentials.password)
        return access_login(credentials.username,credentials.password)
    except AccessDenied as exc:
        raise HTTPException(status_code=401,detail='账号或密码错误') from exc


# G1-G/2: OIDC is local-only and requires pre-provisioned PG subject bindings.
# A signed identity token NEVER directly grants a store or creates an account.
class OIDCComplete(BaseModel):
    code: str=Field(min_length=1,max_length=2048)
    state: str=Field(min_length=30,max_length=200)


def _require_oidc():
    _require_secure()
    if os.getenv('RENEWAL_AUTH_BACKEND')!='oidc':
        raise HTTPException(404,'认证方式未启用')


@app.get('/api/auth/methods')
def auth_methods():
    _require_secure()
    return {'method':'oidc' if os.getenv('RENEWAL_AUTH_BACKEND')=='oidc' else 'password',
            'public_release':'NO_GO'}


@app.post('/api/auth/oidc/start')
def oidc_start():
    _require_oidc()
    from .oidc import OIDCConfig, start, OIDCRejected
    try:
        url,cookie=start(os.environ['RENEWAL_PG_AUTH_DSN'],OIDCConfig.from_env())
    except OIDCRejected as exc:
        raise HTTPException(503,str(exc)) from exc
    response=JSONResponse({'authorization_url':url},headers={'Cache-Control':'no-store'})
    response.set_cookie('renewal_oidc_csrf',cookie,httponly=True,samesite='lax',
                        secure=False,path='/',max_age=300)
    return response


@app.post('/api/auth/oidc/complete')
def oidc_complete(data:OIDCComplete,request:Request):
    _require_oidc()
    from .oidc import OIDCConfig, complete, OIDCRejected
    try:
        result=complete(os.environ['RENEWAL_PG_AUTH_DSN'],OIDCConfig.from_env(),
                        data.state,request.cookies.get('renewal_oidc_csrf',''),data.code)
    except (OIDCRejected,AccessDenied) as exc:
        raise HTTPException(401,'外部身份未验证或未授权') from exc
    response=JSONResponse(result,headers={'Cache-Control':'no-store'})
    response.delete_cookie('renewal_oidc_csrf',path='/')
    return response


@app.post('/api/auth/logout')
def local_logout(request:Request):
    _require_secure()
    try:
        if _pg_auth_active():
            from .pg_auth import logout
            logout(os.environ['RENEWAL_PG_AUTH_DSN'],_bearer(request))
        else: access_logout(_bearer(request))
    except AccessDenied as exc: raise HTTPException(status_code=401,detail='未认证') from exc
    return {'ok':True}


@app.get('/api/v1/me')
def local_me(request:Request):
    _require_secure()
    try:
        if _pg_auth_active():
            from .pg_auth import identity
            return identity(os.environ['RENEWAL_PG_AUTH_DSN'],_bearer(request))
        return access_identity(_bearer(request))
    except AccessDenied as exc: raise HTTPException(status_code=401,detail='未认证') from exc


def _secure_membership(request:Request,store_id:str,roles=None):
    _require_secure()
    if _pg_auth_active():
        # Legacy store-only routes are ambiguous when two orgs share a store ID.
        raise HTTPException(404,'旧版门店接口已禁用')
    try:
        return authorize_store(_bearer(request),store_id,roles)
    except AccessDenied as exc:
        if str(exc)=='没有此门店权限':raise HTTPException(status_code=403,detail='没有此门店权限') from exc
        raise HTTPException(status_code=401,detail='未认证') from exc


@app.get('/api/v1/stores/{store_id}/opportunities')
def secured_opportunities(store_id:str,request:Request):
    principal=_secure_membership(request,store_id,{'staff','manager'})
    return {'store_id':store_id,'items':scoped_opportunities(store_id,owner=principal['user_id'] if principal['role']=='staff' else None)}


@app.get('/api/v1/stores/{store_id}/tasks')
def secured_tasks(store_id:str,request:Request):
    principal=_secure_membership(request,store_id,{'staff','manager'})
    return {'store_id':store_id,'items':scoped_tasks(store_id,owner=principal['user_id'] if principal['role']=='staff' else None)}


@app.get('/api/v1/stores/{store_id}/management')
def secured_management(store_id:str,request:Request):
    _secure_membership(request,store_id,{'manager'})
    return manager_snapshot(store_id=store_id)

# G1-C: trusted local bearer -> PostgreSQL tenant scope. These are NOT public APIs.
# G1-A SQLite stores only local authentication; G1-B PostgreSQL stores business
# facts. Both membership records must agree; org is additionally checked in PG.
class PgTaskRequest(BaseModel):
    opportunity_id: str=Field(min_length=2,max_length=64)
    task_id: str=Field(min_length=2,max_length=64)
    assigned_user_id: str=Field(min_length=2,max_length=64)
    due_on: date

class PgFollowupRequest(BaseModel):
    opportunity_id: str=Field(min_length=2,max_length=64)
    followup_id: str=Field(min_length=2,max_length=64)
    result: str
    note: str=Field(default='',max_length=1000)

class PgContractRequest(BaseModel):
    opportunity_id: str=Field(min_length=2,max_length=64)
    contract_id: str=Field(min_length=2,max_length=64)
    signed_on: date
    amount_cents: int=Field(gt=0,le=100000000)

class PgCashRequest(BaseModel):
    contract_id: str=Field(min_length=2,max_length=64)
    event_id: str=Field(min_length=2,max_length=64)
    occurred_on: date
    kind: str
    amount_cents: int=Field(gt=0,le=100000000)
    refund_of: str | None = None


def _g1c_scope(request:Request,org_id:str,store_id:str):
    # Fail closed on unavailable DB; never fallback to SQLite business records.
    if os.getenv('RENEWAL_RUNTIME_MODE') != 'secure_local':
        raise HTTPException(404,'接口不存在')
    from .pg_store import TenantScope,TenantAccessError,tenant_transaction
    if _pg_auth_active():
        from .pg_auth import authorize_store
        try:
            principal=authorize_store(os.environ['RENEWAL_PG_AUTH_DSN'],_bearer(request),org_id,store_id)
        except AccessDenied as exc:
            if str(exc)=='未认证':
                raise HTTPException(401,'未认证') from exc
            raise HTTPException(403,'没有该机构/门店的授权') from exc
    else:
        principal=_secure_membership(request,store_id,{'manager','staff'})
    dsn=os.getenv('RENEWAL_PG_APP_DSN','')
    if not dsn:
        raise HTTPException(503,'PostgreSQL尚未配置')
    try:
        scope=TenantScope(org_id,store_id,principal['user_id'])
        with tenant_transaction(dsn,scope) as con:
            role=con.execute('SELECT renewalos.actor_store_role()').fetchone()[0]
            if role!=principal['role']:
                raise TenantAccessError('membership role mismatch')
        return dsn,scope
    except (TenantAccessError,ValueError) as exc:
        raise HTTPException(403,'没有该机构/门店的授权') from exc


def _g1c_execute(fn,*args):
    from .pg_store import TenantAccessError
    from .pg_business import BusinessConflict,BusinessMissing
    try:
        return fn(*args)
    except TenantAccessError as exc:
        raise HTTPException(403,'操作权限不足') from exc
    except BusinessMissing as exc:
        raise HTTPException(404,'资源不存在或未授权') from exc
    except BusinessConflict as exc:
        raise HTTPException(409,str(exc)) from exc
    except (ValueError,TypeError) as exc:
        raise HTTPException(422,str(exc)) from exc
    except Exception as exc:
        # The DB schema/role might be unavailable or an RLS/constraint may deny
        # a write. No SQL or resource existence details may reach the client.
        from .pg_store import _driver
        pg=_driver()
        if isinstance(exc,(pg.errors.InsufficientPrivilege,pg.errors.ForeignKeyViolation,
                            pg.errors.CheckViolation,pg.errors.UniqueViolation)):
            raise HTTPException(409,'数据库安全或资金约束拒绝该操作') from exc
        raise


@app.get('/api/v1/orgs/{org_id}/stores/{store_id}/opportunities')
def pg_opportunities(org_id:str,store_id:str,request:Request):
    from .pg_store import list_store_opportunities
    dsn,scope=_g1c_scope(request,org_id,store_id)
    return {'items':_g1c_execute(list_store_opportunities,dsn,scope)}

@app.get('/api/v1/orgs/{org_id}/stores/{store_id}/opportunities/{opportunity_id}')
def pg_opportunity_detail(org_id:str,store_id:str,opportunity_id:str,request:Request):
    from .pg_business import opportunity_workbench
    dsn,scope=_g1c_scope(request,org_id,store_id)
    return _g1c_execute(opportunity_workbench,dsn,scope,opportunity_id)

@app.get('/api/v1/orgs/{org_id}/stores/{store_id}/tasks')
def pg_tasks(org_id:str,store_id:str,request:Request):
    from .pg_store import list_assigned_tasks
    dsn,scope=_g1c_scope(request,org_id,store_id)
    return {'items':_g1c_execute(list_assigned_tasks,dsn,scope)}

@app.get('/api/v1/orgs/{org_id}/stores/{store_id}/management')
def pg_manager(org_id:str,store_id:str,request:Request):
    from .pg_business import manager_snapshot
    dsn,scope=_g1c_scope(request,org_id,store_id)
    return _g1c_execute(manager_snapshot,dsn,scope)

@app.post('/api/v1/orgs/{org_id}/stores/{store_id}/tasks')
def pg_task_create(org_id:str,store_id:str,request:Request,data:PgTaskRequest):
    from .pg_business import assign_task
    dsn,scope=_g1c_scope(request,org_id,store_id)
    return _g1c_execute(assign_task,dsn,scope,data.opportunity_id,data.task_id,data.assigned_user_id,data.due_on)

@app.post('/api/v1/orgs/{org_id}/stores/{store_id}/followups')
def pg_followup_create(org_id:str,store_id:str,request:Request,data:PgFollowupRequest):
    from .pg_business import record_followup
    dsn,scope=_g1c_scope(request,org_id,store_id)
    return _g1c_execute(record_followup,dsn,scope,data.opportunity_id,data.followup_id,data.result,data.note)

@app.post('/api/v1/orgs/{org_id}/stores/{store_id}/contracts')
def pg_contract_create(org_id:str,store_id:str,request:Request,data:PgContractRequest):
    from .pg_business import sign_synthetic_contract
    dsn,scope=_g1c_scope(request,org_id,store_id)
    return _g1c_execute(sign_synthetic_contract,dsn,scope,data.opportunity_id,data.contract_id,data.signed_on,data.amount_cents)

@app.post('/api/v1/orgs/{org_id}/stores/{store_id}/cash-events')
def pg_cash_create(org_id:str,store_id:str,request:Request,data:PgCashRequest):
    from .pg_business import record_synthetic_cash
    dsn,scope=_g1c_scope(request,org_id,store_id)
    return _g1c_execute(record_synthetic_cash,dsn,scope,data.contract_id,data.event_id,
                        data.kind,data.amount_cents,data.occurred_on,data.refund_of)

@app.get("/api/ready")
def ready():
    status=local_readiness()
    return JSONResponse(status,status_code=200 if status["ready"] else 503,headers={"Cache-Control":"no-store"})

@app.get("/api/health")
def health():
    mode=os.getenv("RENEWAL_RUNTIME_MODE", "demo")
    return {"ok":True,"mode":"SECURE_LOCAL_ALPHA" if mode=="secure_local" else "LOCAL_DEMO",
            "pg_configured":bool(os.getenv("RENEWAL_PG_APP_DSN")) and mode=="secure_local",
            "ai_configured":all((os.getenv("RENEWAL_AI_BASE_URL"),os.getenv("RENEWAL_AI_API_KEY"),os.getenv("RENEWAL_AI_MODEL")))}
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

# G0.7 local work queue. Owner is an alias, NOT an authenticated identity.
@app.get('/api/tasks')
def tasks(store_id: str|None=None, owner: str|None=None, status: str|None=None, due_bucket: str|None=None):
    if status and status not in ('all','open','in_progress','waiting','done','cancelled'):
        raise HTTPException(422,'任务状态无效')
    if due_bucket and due_bucket not in ('all','overdue','today','upcoming','resolved'):
        raise HTTPException(422,'截止日期筛选无效')
    if any(len(v)>100 for v in (store_id or '',owner or '')):raise HTTPException(422,'筛选字段过长')
    return {'items':list_tasks(store_id,owner,status,due_bucket),
            'summary':task_summary(store_id,owner)}

@app.post('/api/tasks')
def new_task(data:TaskCreate):
    try:return create_task(data.opportunity_id,data.owner,data.due_on.isoformat(),data.note)
    except TaskRuleError as e:raise HTTPException(422,str(e)) from e

@app.patch('/api/tasks/{task_id}')
def edit_task(task_id:str,data:TaskUpdate):
    try:return update_task(task_id,data.actor,owner=data.owner,
             due_on=data.due_on.isoformat() if data.due_on else None,status=data.status,note=data.note)
    except TaskRuleError as e:raise HTTPException(422,str(e)) from e

@app.get('/api/tasks/{task_id}/history')
def history_task(task_id:str):
    try:return {'items':task_history(task_id)}
    except TaskRuleError as e:raise HTTPException(404,str(e)) from e

@app.post('/api/tasks/{task_id}/followups')
def task_followup(task_id:str,data:TaskFollowup):
    try:return record_task_followup(task_id,data.actor,data.status,data.note)
    except TaskRuleError as e:raise HTTPException(422,str(e)) from e

@app.get("/api/report")
def metrics():return report()

@app.get("/api/management/overview")
def manager_overview(store_id: str | None = None):
    try: return manager_snapshot(store_id=store_id)
    except ValueError as e: raise HTTPException(422,str(e)) from e

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
        when=now_iso()
        con.execute("INSERT INTO followups(opportunity_id,owner,status,note,logged_at) VALUES(?,?,?,?,?)",
                    (data.opportunity_id,data.owner,data.status,data.note,when))
        # Legacy opportunity followup stays in sync with assigned task.
        task=con.execute('SELECT task_id,status FROM work_tasks WHERE opportunity_id=?',
                         (data.opportunity_id,)).fetchone()
        if task and task['status'] in OPEN:
            next_status=FOLLOWUP_TO_TASK[data.status]
            con.execute('UPDATE work_tasks SET status=?,updated_at=?,resolved_at=? WHERE task_id=?',
                        (next_status,when,when if next_status in ('done','cancelled') else None,task['task_id']))
            con.execute('INSERT INTO work_task_events(task_id,actor,event_kind,details,logged_at) VALUES(?,?,?,?,?)',
                        (task['task_id'],data.owner,'followup',data.status+(' · '+data.note if data.note else ''),when))
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
