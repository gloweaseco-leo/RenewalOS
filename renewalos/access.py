"""G1-A local-only authentication and store-scoped read access.

No production claims: SQLite sessions, no external identity provider and no public hosting.
Every tenant-facing query must be scoped at SQL level using authenticated memberships.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from .db import connect

ITERATIONS = 390_000
SESSION_TTL_HOURS = 8
ALLOWED_ROLES = frozenset({'staff', 'manager', 'auditor'})
ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{2,64}$')

DDL = """
CREATE TABLE IF NOT EXISTS access_users (
 user_id TEXT PRIMARY KEY,
 password_salt BLOB NOT NULL,
 password_hash BLOB NOT NULL,
 iterations INTEGER NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN(0,1))
);
CREATE TABLE IF NOT EXISTS access_memberships (
 user_id TEXT NOT NULL REFERENCES access_users(user_id),
 store_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('staff','manager','auditor')),
 PRIMARY KEY(user_id,store_id)
);
CREATE TABLE IF NOT EXISTS access_sessions (
 token_hash TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES access_users(user_id),
 expires_on TEXT NOT NULL,
 revoked_on TEXT,
 created_on TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_access_session_user ON access_sessions(user_id,expires_on);
CREATE TABLE IF NOT EXISTS access_audit (
 audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id TEXT,
 action TEXT NOT NULL,
 store_id TEXT,
 occurred_on TEXT NOT NULL,
 result TEXT NOT NULL
);
"""

class AccessDenied(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().isoformat()


def initialize_access(path=None):
    with connect(path) as con:
        con.executescript(DDL)


def _derive(password, salt, count):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, count)


def create_local_user(user_id, password, memberships, path=None):
    """Explicit local provisioning by administrator; never exposed via HTTP."""
    if not ID_PATTERN.fullmatch(user_id) or len(password) < 12 or len(password) > 256:
        raise ValueError('账号仅允许2-64位英数/_/-；密码最少12位')
    if not memberships or not all(ID_PATTERN.fullmatch(store) and role in ALLOWED_ROLES
                                  for store, role in memberships.items()):
        raise ValueError('门店和角色无效')
    salt = secrets.token_bytes(16)
    hashed = _derive(password, salt, ITERATIONS)
    with connect(path) as con:
        con.execute('INSERT INTO access_users(user_id,password_salt,password_hash,iterations) VALUES(?,?,?,?)',
                    (user_id,salt,hashed,ITERATIONS))
        for store, role in memberships.items():
            con.execute('INSERT INTO access_memberships(user_id,store_id,role) VALUES(?,?,?)',
                        (user_id,store,role))
        con.execute('INSERT INTO access_audit(user_id,action,occurred_on,result) VALUES(?,?,?,?)',
                    (user_id,'provision',iso_now(),'allowed'))


def _log(con, user, action, result, store=None):
    con.execute('INSERT INTO access_audit(user_id,action,store_id,occurred_on,result) VALUES(?,?,?,?,?)',
                (user,action,store,iso_now(),result))


def login(user_id, password, path=None):
    """Opaque bearer session: only SHA-256 of token retained, never raw token."""
    if not isinstance(user_id,str) or not isinstance(password,str):
        raise AccessDenied('账号或密码错误')
    with connect(path) as con:
        row = con.execute('SELECT * FROM access_users WHERE user_id=? AND enabled=1',(user_id,)).fetchone()
        # Equalise work for unknown users to limit account enumeration timing signals.
        salt = row['password_salt'] if row else b'\x00'*16
        loops = row['iterations'] if row else ITERATIONS
        calculated = _derive(password, salt, loops)
        if row is None or not hmac.compare_digest(calculated, row['password_hash']):
            _log(con,user_id[:64] if ID_PATTERN.fullmatch(user_id) else None,'login','denied')
            con.commit()
            raise AccessDenied('账号或密码错误')
        token = secrets.token_urlsafe(32)
        until = (utc_now()+timedelta(hours=SESSION_TTL_HOURS)).isoformat()
        con.execute('INSERT INTO access_sessions(token_hash,user_id,expires_on,created_on) VALUES(?,?,?,?)',
                    (hashlib.sha256(token.encode()).hexdigest(),user_id,until,iso_now()))
        _log(con,user_id,'login','allowed')
        roles = {r['store_id']:r['role'] for r in con.execute('SELECT store_id,role FROM access_memberships WHERE user_id=?',(user_id,))}
        return {'access_token':token,'token_type':'bearer','expires_on':until,
                'user_id':user_id,'memberships':roles}


def _token_row(con, bearer):
    if not isinstance(bearer,str) or len(bearer)>256 or len(bearer)<24:
        raise AccessDenied('未认证')
    digest=hashlib.sha256(bearer.encode()).hexdigest()
    row=con.execute('''SELECT s.user_id,s.expires_on,u.enabled
                       FROM access_sessions s JOIN access_users u ON u.user_id=s.user_id
                       WHERE s.token_hash=? AND s.revoked_on IS NULL''',(digest,)).fetchone()
    if row is None or not row['enabled'] or datetime.fromisoformat(row['expires_on']) <= utc_now():
        raise AccessDenied('会话无效或已过期')
    return row


def identity(token,path=None):
    with connect(path) as con:
        row=_token_row(con,token)
        memberships={x['store_id']:x['role'] for x in con.execute(
            'SELECT store_id,role FROM access_memberships WHERE user_id=?',(row['user_id'],))}
        return {'user_id':row['user_id'],'memberships':memberships}


def authorize_store(token,store_id,required_roles=None,path=None):
    """No resource details returned if membership missing, disabled or insufficient."""
    with connect(path) as con:
        principal=_token_row(con,token)
        role=con.execute('SELECT role FROM access_memberships WHERE user_id=? AND store_id=?',
                         (principal['user_id'],store_id)).fetchone()
        permitted = role is not None and (required_roles is None or role['role'] in required_roles)
        _log(con,principal['user_id'],'store_access','allowed' if permitted else 'denied',store_id[:64])
        if not permitted:
            con.commit()  # denied attempts must survive the exception for auditing
            raise AccessDenied('没有此门店权限')
        return {'user_id':principal['user_id'],'role':role['role'],'store_id':store_id}


def logout(token,path=None):
    with connect(path) as con:
        row=_token_row(con,token)
        con.execute('UPDATE access_sessions SET revoked_on=? WHERE token_hash=?',
                    (iso_now(),hashlib.sha256(token.encode()).hexdigest()))
        _log(con,row['user_id'],'logout','allowed')


def scoped_opportunities(store_id, owner=None, path=None):
    with connect(path) as con:
        sql = '''SELECT o.opportunity_id,o.package_id,o.priority,o.reason,
             o.is_active,o.updated_at,p.course_type,l.learner_id,l.guardian_alias,l.store_id
             FROM opportunities o JOIN learners l ON l.learner_id=o.learner_id
             JOIN packages p ON p.package_id=o.package_id
             WHERE l.store_id=?'''
        args=(store_id,)
        if owner is not None:
            sql += ' AND EXISTS (SELECT 1 FROM work_tasks t WHERE t.opportunity_id=o.opportunity_id AND t.store_id=? AND t.owner=?)'
            args += (store_id,owner)
        sql += ' ORDER BY o.priority DESC,o.opportunity_id'
        return [dict(r) for r in con.execute(sql,args)]


def scoped_tasks(store_id, owner=None, path=None):
    with connect(path) as con:
        sql='''SELECT t.task_id,t.opportunity_id,t.owner,t.due_on,
             t.status,t.updated_at,t.store_id FROM work_tasks t
             JOIN opportunities o ON o.opportunity_id=t.opportunity_id
             JOIN learners l ON l.learner_id=o.learner_id
             WHERE t.store_id=? AND l.store_id=?'''
        args=(store_id,store_id)
        if owner is not None:
            sql+=' AND t.owner=?'
            args+=(owner,)
        sql+=' ORDER BY t.due_on,t.task_id'
        return [dict(r) for r in con.execute(sql,args)]
