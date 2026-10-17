"""RenewalOS local demo API. Never expose on the public internet."""
import csv
import io
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
from .ai import suggest,AIUnavailable

ROOT=Path(__file__).resolve().parent.parent
SCHEMAS={
 "learners":{"learner_id","family_id","guardian_alias","store_id","contact_consent"},
 "packages":{"package_id","learner_id","course_type","purchased_on","expires_on","purchased_sessions","remaining_sessions","price_cny"},
 "attendance":{"event_id","learner_id","session_date","status"},
 "renewals":{"renewal_id","learner_id","source_package_id","paid_on","amount_cny","status"}
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
    raise ValueError("未知数据类型")

@asynccontextmanager
async def lifespan(app):
    initialize()
    yield

app=FastAPI(title="RenewalOS Demo",version="0.1.0",lifespan=lifespan,
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
def opportunities():return {"items":list_opportunities()}
@app.get("/api/followups/{opportunity_id}")
def followup_history(opportunity_id: str):
    return {"items": list_followups(opportunity_id=opportunity_id)}

@app.get("/api/report")
def metrics():return report()

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
            if not all(v is not None and v!="" for v in vals):raise ValueError(f"第{row_num}行包含空值")
            items.append(vals)
        if not items: raise ValueError("CSV无数据行")
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

@app.post("/api/opportunities/{opportunity_id}/ai-advice")
def make_ai_advice(opportunity_id:str):
    with connect() as con:
        row=con.execute("""SELECT o.signals_json,p.course_type,a.arm FROM opportunities o
         JOIN packages p ON p.package_id=o.package_id JOIN learners l ON o.learner_id=l.learner_id
         JOIN experiment_assignments a ON a.family_id=l.family_id WHERE o.opportunity_id=? AND o.is_active=1""",(opportunity_id,)).fetchone()
        if not row:raise HTTPException(404,"机会不存在")
        if row["arm"]!="ai":raise HTTPException(403,"只有AI实验组可使用模型建议，避免实验串组。")
        import json
        try:advice,source=suggest(json.loads(row["signals_json"]),row["course_type"])
        except AIUnavailable as e:raise HTTPException(409,str(e)) from e
        con.execute("""INSERT INTO ai_advice(opportunity_id,advice,source,created_at) VALUES(?,?,?,?)
           ON CONFLICT(opportunity_id) DO UPDATE SET advice=excluded.advice,source=excluded.source,created_at=excluded.created_at""",
           (opportunity_id,advice,source,now_iso()))
    return {"advice":advice,"source":source}