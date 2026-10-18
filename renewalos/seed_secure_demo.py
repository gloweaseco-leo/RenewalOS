"""Opt-in synthetic-only seed for G1-A local role testing; never via HTTP."""
import argparse
import os
from .db import connect, initialize
from .access import initialize_access
from .demo import load_demo


def run(confirmed=False):
    if not confirmed or os.getenv('RENEWAL_RUNTIME_MODE')!='secure_local':
        raise RuntimeError('仅允许显式确认的安全本地合成数据模式')
    if not os.getenv('RENEWAL_DB_PATH'):
        raise RuntimeError('必须明确设置 RENEWAL_DB_PATH，不允许改写项目默认数据库')
    initialize();initialize_access()
    with connect() as con:
        existing=con.execute('SELECT COUNT(*) AS n FROM learners').fetchone()['n']
    if existing:
        raise RuntimeError('目标数据库已有学员数据，拒绝覆盖')
    return load_demo()


def main():
    p=argparse.ArgumentParser(description='Explicitly seed a new LOCAL database with synthetic records')
    p.add_argument('--confirm-synthetic-only',action='store_true')
    args=p.parse_args()
    print('Generated synthetic opportunities:',run(args.confirm_synthetic_only))

if __name__=='__main__':main()
