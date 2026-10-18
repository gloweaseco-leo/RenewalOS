"""Dedicated PostgreSQL credentials/session adapter for local synthetic tests.

Requires RENEWAL_PG_AUTH_DSN using a dedicated least-privilege identity DB role;
never use the business or migration connection as the identity credential.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone, timedelta
from .access import AccessDenied, ITERATIONS
from .pg_store import _driver

ID = re.compile(r'^[A-Za-z0-9_-]{2,64}$')


def digest(token):
    if not isinstance(token,str) or not 24 <= len(token) <= 256:
        raise AccessDenied('未认证')
    return hashlib.sha256(token.encode()).hexdigest()


def memberships(con, user):
    rows=con.execute('SELECT org_id,store_id,role FROM renewalos_auth.active_memberships(%s)',(user,)).fetchall()
    return {org+':'+store:role for org,store,role in rows}


def audit(con,user,action,outcome,org=None,store=None):
    con.execute('''INSERT INTO renewalos_auth.audit(user_id,action,outcome,org_id,store_id)
                   VALUES(%s,%s,%s,%s,%s)''',(user,action,outcome,org,store))


def login(dsn,user,password):
    if not isinstance(user,str) or not ID.fullmatch(user) or not isinstance(password,str) or len(password)>256:
        raise AccessDenied('账号或密码错误')
    with _driver().connect(dsn) as con:
        row=con.execute('SELECT password_salt,password_hash,iterations FROM renewalos_auth.credentials WHERE user_id=%s',(user,)).fetchone()
        salt=bytes(row[0]) if row else b'\0'*16
        count=row[2] if row else ITERATIONS
        hashed=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,count)
        verified=bool(row and hmac.compare_digest(hashed,bytes(row[1])))
        allowed=memberships(con,user) if verified else {}
        if not verified or not allowed:
            audit(con,user,'login','denied'); con.commit()
            raise AccessDenied('账号或密码错误')
        token=secrets.token_urlsafe(32)
        until=datetime.now(timezone.utc)+timedelta(hours=8)
        con.execute('INSERT INTO renewalos_auth.sessions(token_hash,user_id,expires_at) VALUES(%s,%s,%s)',(digest(token),user,until))
        audit(con,user,'login','allowed')
        return {'access_token':token,'token_type':'bearer','expires_on':until.isoformat(),
                'user_id':user,'memberships':allowed,'identity_backend':'postgres'}


def _actor(con,token):
    row=con.execute('''SELECT s.user_id FROM renewalos_auth.sessions s
        WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>now()
          AND (s.oidc_issuer IS NULL OR EXISTS (
            SELECT 1 FROM renewalos_auth.oidc_bindings b
            WHERE b.issuer=s.oidc_issuer AND b.subject=s.oidc_subject
              AND b.user_id=s.user_id AND b.enabled))''',(digest(token),)).fetchone()
    if not row:raise AccessDenied('未认证')
    allowed=memberships(con,row[0])
    if not allowed:raise AccessDenied('未认证')
    return row[0],allowed


def identity(dsn,token):
    with _driver().connect(dsn) as con:
        user,allowed=_actor(con,token)
        return {'user_id':user,'memberships':allowed,'identity_backend':'postgres'}


def authorize_store(dsn,token,org,store,roles=('manager','staff')):
    if not isinstance(org,str) or not isinstance(store,str) or not ID.fullmatch(org) or not ID.fullmatch(store):
        raise AccessDenied('没有此机构/门店权限')
    with _driver().connect(dsn) as con:
        user,allowed=_actor(con,token)
        role=allowed.get(org+':'+store)
        permitted=role in roles
        audit(con,user,'authz','allowed' if permitted else 'denied',org,store)
        if not permitted:
            con.commit()
            raise AccessDenied('没有此机构/门店权限')
        return {'user_id':user,'org_id':org,'store_id':store,'role':role}


def logout(dsn,token):
    with _driver().connect(dsn) as con:
        user,_=_actor(con,token)
        con.execute('UPDATE renewalos_auth.sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL',(digest(token),))
        audit(con,user,'logout','allowed')
