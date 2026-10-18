"""Local-only release audit. Exit zero only for valid local-only configuration.

Production is ALWAYS a NO-GO regardless of this command's success.
"""
import json
import os
from renewalos.release_gate import assert_dedicated_pg_roles, assert_local_only, ReleaseBlocked


def audit(environ=None):
    env=os.environ if environ is None else environ
    issues=[]
    try: assert_local_only(env)
    except ReleaseBlocked: issues.append('PUBLIC_DEPLOYMENT_BLOCKED')
    if env.get('RENEWAL_RUNTIME_MODE')!='secure_local':issues.append('SECURE_LOCAL_REQUIRED')
    if env.get('RENEWAL_AUTH_BACKEND') not in ('postgres','oidc'):issues.append('POSTGRES_IDENTITY_REQUIRED')
    if env.get('RENEWAL_AUTH_BACKEND')=='oidc':
        try:
            from renewalos.oidc import OIDCConfig
            OIDCConfig.from_env(env)
        except Exception:
            issues.append('OIDC_CONFIG_REQUIRED')
    try: assert_dedicated_pg_roles(env)
    except ReleaseBlocked:issues.append('DEDICATED_PG_ROLES_REQUIRED')
    return {'public_release':'NO_GO','local_synthetic_ready_for_db_check':not issues,'issues':issues,
            'unresolved_gates':['OIDC_MFA','OIDC_PROVIDER_ACCEPTANCE','LAWFUL_DATA_IMPORT','ENCRYPTED_BACKUP_RESTORE',
                                'SECRET_ROTATION','PRODUCTION_OPERATIONS']}


def main():
    report=audit()
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0 if report['local_synthetic_ready_for_db_check'] else 2

if __name__=='__main__':raise SystemExit(main())
