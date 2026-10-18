"""Real loopback HTTP smoke using PostgreSQL auth and business connections.

Runs only against CI disposable PostgreSQL and synthetic fixtures; spawns uvicorn
and exercises the entire business workflow over TCP, not TestClient/ASGI mock.
"""
import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def main():
    if os.getenv('CI') != 'true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY':
        raise SystemExit('Refuse HTTP E2E outside disposable CI')
    import psycopg
    import httpx
    from datetime import date
    org='e2eorg';store='pool';uid='e2emanager';staff='e2estaff'
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as db:
        db.execute('INSERT INTO renewalos.organizations(org_id,label) VALUES(%s,%s)',(org,'synthetic E2E'))
        db.execute('INSERT INTO renewalos.stores(org_id,store_id,label) VALUES(%s,%s,%s)',(org,store,'synthetic pool'))
        for user,role,secret in [(uid,'manager','G1E_Manager_Password_2026'),(staff,'staff','G1E_Staff_Password_2026')]:
            db.execute('INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES(%s,%s)',(user,user))
            db.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES(%s,%s,'member')",(org,user))
            db.execute('INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES(%s,%s,%s,%s)',(org,store,user,role))
            salt=bytes(range(16));pw=hashlib.pbkdf2_hmac('sha256',secret.encode(),salt,390000)
            db.execute('INSERT INTO renewalos_auth.credentials(user_id,password_salt,password_hash,iterations) VALUES(%s,%s,%s,390000)',(user,salt,pw))
        db.execute("INSERT INTO renewalos.households(org_id,store_id,household_id) VALUES(%s,%s,'family01')",(org,store))
        db.execute("INSERT INTO renewalos.learners(org_id,store_id,learner_id,household_id,alias,contact_consent) VALUES(%s,%s,'kid01','family01','Child-01',true)",(org,store))
        db.execute("""INSERT INTO renewalos.course_packages(org_id,store_id,package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cents)
                       VALUES(%s,%s,'package01','kid01','swim','2026-01-01','2026-12-31',20,2,150000)""",(org,store))
        db.execute("INSERT INTO renewalos.renewal_opportunities(org_id,store_id,opportunity_id,source_package_id,learner_id,arm,priority) VALUES(%s,%s,'opportunity01','package01','kid01','rules',85)",(org,store))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'RENEWAL_RUNTIME_MODE':'secure_local','RENEWAL_AUTH_BACKEND':'postgres',
         'RENEWAL_PG_APP_DSN':os.environ['RENEWAL_PG_TEST_DSN'],
         'RENEWAL_DB_PATH':'/proc/g1e_no_sqlite_access.db'}
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','renewalos.main:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    base=f'http://127.0.0.1:{port}'
    try:
        with httpx.Client(base_url=base,timeout=5) as c:
            for i in range(80):
                if proc.poll() is not None:
                    raise AssertionError('Server exited: '+proc.stderr.read().decode(errors='replace')[:3000])
                try:
                    if c.get('/api/health').status_code==200:break
                except httpx.ConnectError:pass
                time.sleep(.2)
            else:raise AssertionError('HTTP server not ready')
            def login(user,pw):
                r=c.post('/api/auth/login',json={'username':user,'password':pw})
                assert r.status_code==200,(r.status_code,r.text)
                return {'Authorization':'Bearer '+r.json()['access_token']}
            man=login(uid,'G1E_Manager_Password_2026');worker=login(staff,'G1E_Staff_Password_2026')
            root=f'/api/v1/orgs/{org}/stores/{store}'
            assert c.get(root+'/opportunities',headers=man).status_code==200
            assert c.get(root+'/opportunities',headers=worker).json()['items']==[]
            assert c.get('/api/v1/stores/pool/tasks',headers=man).status_code==404
            assert c.get('/api/v1/orgs/fakeorg/stores/pool/tasks',headers=man).status_code==403
            task={'opportunity_id':'opportunity01','task_id':'task01','assigned_user_id':staff,'due_on':'2026-11-05'}
            x=c.post(root+'/tasks',headers=man,json=task);assert x.status_code==200,x.text
            assert c.post(root+'/tasks',headers=man,json=task).json()['created'] is False
            assert len(c.get(root+'/tasks',headers=worker).json()['items'])==1
            x=c.post(root+'/followups',headers=worker,json={'opportunity_id':'opportunity01','followup_id':'follow01','result':'contacted','note':'synthetic only'})
            assert x.status_code==200,x.text
            x=c.post(root+'/contracts',headers=man,json={'opportunity_id':'opportunity01','contract_id':'contract01','signed_on':'2026-10-18','amount_cents':100000})
            assert x.status_code==200,x.text
            assert c.get(root+'/opportunities/opportunity01',headers=worker).json()['contract'] is None
            x=c.post(root+'/cash-events',headers=man,json={'contract_id':'contract01','event_id':'pay01','kind':'payment','amount_cents':80000,'occurred_on':'2026-10-18'})
            assert x.status_code==200,x.text
            x=c.post(root+'/cash-events',headers=man,json={'contract_id':'contract01','event_id':'refund01','kind':'refund','amount_cents':20000,'occurred_on':'2026-10-18','refund_of':'pay01'})
            assert x.status_code==200,x.text
            assert c.get(root+'/management',headers=man).json()['synthetic_cash_net_cents']==60000
            assert c.get(root+'/management',headers=worker).status_code==403
            assert c.post('/api/auth/logout',headers=man,json={}).status_code==200
            assert c.get(root+'/opportunities',headers=man).status_code==401
    finally:
        proc.terminate()
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
    print('G1-E real TCP HTTP PostgreSQL auth+business E2E successful')

if __name__=='__main__':main()
