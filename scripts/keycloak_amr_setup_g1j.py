"""Configure real Keycloak OTP authenticator's native AMR reference, CI only.

The ID token's `amr` must reflect a *completed* authenticator execution.
Never fabricate a hardcoded MFA claim or grant users application roles here.
"""
import os
import time
import httpx

IDP='https://127.0.0.1:18443'
REALM='renewalos-ci'
REFERENCE_KEY='default.reference.value'


def run():
    if os.getenv('CI')!='true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP')!='I_ACCEPT_CI_ONLY':
        raise SystemExit('Disposable CI Keycloak only')
    with httpx.Client(timeout=10.0, follow_redirects=False) as cli:
        deadline=time.monotonic()+90
        while True:
            try:
                x=cli.post(IDP+'/realms/master/protocol/openid-connect/token',data={
                    'client_id':'admin-cli','grant_type':'password','username':'synthetic-admin',
                    'password':'Only-In-Disposable-CI'})
                if x.status_code==200:
                    break
                if x.status_code in (400,401,403):
                    raise AssertionError('CI Keycloak bootstrap administrator not authorized')
            except httpx.RequestError:
                pass
            if time.monotonic()>deadline:
                raise RuntimeError('Disposable Keycloak admin access unavailable')
            time.sleep(2)
        bearer=x.json().get('access_token')
        if not isinstance(bearer,str) or not bearer:
            raise RuntimeError('No test Keycloak management token')
        headers={'Authorization':'Bearer '+bearer}
        base=IDP+'/admin/realms/'+REALM
        flows=cli.get(base+'/authentication/flows',headers=headers)
        flows.raise_for_status()
        candidates=[]
        for flow in flows.json():
            alias=flow.get('alias','')
            # Inspect Keycloak's built-in browser/2FA tree only.
            if not (alias=='browser' or 'browser' in alias.lower()):
                continue
            r=cli.get(base+'/authentication/flows/'+alias+'/executions',headers=headers)
            r.raise_for_status()
            for execution in r.json():
                if execution.get('providerId')=='auth-otp-form':
                    candidates.append(execution['id'])
        ids=set(candidates)
        if len(ids)!=1:
            raise AssertionError('Unable to select exactly one Keycloak browser OTP execution; count '+str(len(ids)))
        otp_id=ids.pop()
        posted=cli.post(base+'/authentication/executions/'+otp_id+'/config',json={
            'alias':'g1j-native-otp-reference',
            'config':{REFERENCE_KEY:'otp'}
        },headers=headers)
        if posted.status_code not in (200,201,204):
            raise AssertionError('Keycloak rejected native OTP AMR execution reference: '+str(posted.status_code))
        # Only a real completed OTP authenticator produces amr=otp; no custom
        # hardcoded claim or synthetic token assertions may substitute for it.
    print('G1-J native Keycloak OTP authenticator AMR reference configured (CI only)',flush=True)


if __name__=='__main__':run()
