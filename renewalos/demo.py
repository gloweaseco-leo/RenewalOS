"""Synthetic, reproducible learner data. Absolutely no real customer data."""
from datetime import date,timedelta
from .db import connect
from .core import recompute

def load_demo(path=None,today=None):
    today=today or date.today()
    with connect(path) as con:
        for table in ("work_task_events","work_tasks","ai_advice_reviews","ai_advice_attempts","cash_events","renewal_contracts","renewal_cohort_members","cohorts","ai_advice","followups","opportunities","experiment_assignments","renewals","attendance","packages","learners"):
            con.execute(f"DELETE FROM {table}")
        for i in range(1,37):
            learner=f"L{i:03d}"; pkg=f"PK{i:03d}"; family=f"F{((i-1)//2)+1:03d}"
            consent=0 if i in (12,24) else 1
            con.execute("INSERT INTO learners VALUES(?,?,?,?,?)",(learner,family,f"监护人{i:02d}","DEMO-STORE",consent))
            expires=today+timedelta(days=(i*7)%48-6)
            purchased=today-timedelta(days=90)
            remaining=(i*3)%12
            con.execute("INSERT INTO packages VALUES(?,?,?,?,?,?,?,?)",
                        (pkg,learner,"青少年游泳" if i%3 else "少儿体能",purchased.isoformat(),expires.isoformat(),24,remaining,round((1800+i*35)*100)))
            for w in range(8):
                # First four weeks mostly regular, recent four weeks uneven for selected learners.
                count = (0 if (i%4==0 and w>=4) else 1)
                if i%5==0 and w>=4:count=0
                for j in range(count):
                    day=today-timedelta(days=54-w*7+j)
                    if day<=today:
                        event=f"E{i:03d}-{w}-{j}"
                        con.execute("INSERT INTO attendance VALUES(?,?,?,?)",(event,learner,day.isoformat(),"present"))
        # A renewal already paid; it must disappear from the active opportunity pool.
        con.execute("INSERT INTO renewals VALUES(?,?,?,?,?,?)",
                    ("R001","L001","PK001",(today-timedelta(days=2)).isoformat(),285000,"paid"))
    return recompute(path,today)
