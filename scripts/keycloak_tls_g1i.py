"""Loopback-only throwaway HTTPS gateway for Keycloak integration CI.

Do not use for preproduction or production; never expose 18443 publicly.
"""
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_DIR=Path('/tmp/renewalos-g1i-cert')


def create_certificate():
    CERT_DIR.mkdir(mode=0o700, exist_ok=True)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'RenewalOS synthetic Keycloak CI')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(hours=3))
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
          .sign(key,hashes.SHA256()))
    (CERT_DIR/'key.pem').write_bytes(key.private_bytes(
        serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    (CERT_DIR/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(CERT_DIR/'key.pem',0o600)
    print(str(CERT_DIR/'cert.pem'),flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def do_GET(self):self._forward()
    def do_POST(self):self._forward()
    def log_message(self,fmt,*args):pass  # Do not log OAuth code, cookies or tokens
    def _forward(self):
        # CI-only Keycloak configuration needs access to its test realm's
        # authenticator metadata, not to account, client or identity admin APIs.
        # This allowlist is a narrow exception for the disposable 18443 proxy.
        path=self.path.split('?',1)[0]
        auth_config_prefix='/admin/realms/renewalos-ci/authentication/'
        is_public=path.startswith('/realms/')
        is_auth_config=(path.startswith(auth_config_prefix) and
                        (path==auth_config_prefix+'flows' or
                         (path.startswith(auth_config_prefix+'flows/') and
                          path.endswith('/executions')) or
                         (path.startswith(auth_config_prefix+'executions/') and
                          path.endswith('/config'))))
        if len(self.path)>4096 or not (is_public or is_auth_config):
            self.send_error(404);return
        length=int(self.headers.get('content-length','0'))
        if length>131072:
            self.send_error(413);return
        raw=self.rfile.read(length) if length else b''
        blocked={'host','connection','transfer-encoding','content-length','x-forwarded-proto',
                 'x-forwarded-host','x-forwarded-port','x-forwarded-for','forwarded','accept-encoding'}
        headers={k:v for k,v in self.headers.items() if k.lower() not in blocked}
        headers.update({'Host':'127.0.0.1:18443','X-Forwarded-Proto':'https',
                        'X-Forwarded-Port':'18443','X-Forwarded-Host':'127.0.0.1:18443'})
        try:
            with httpx.Client(timeout=12.0,follow_redirects=False,trust_env=False) as client:
                response=client.request(self.command,'http://127.0.0.1:18080'+self.path,
                                        headers=headers,content=raw)
            self.send_response(response.status_code)
            omit={'content-length','transfer-encoding','connection','content-encoding','date','server'}
            for key,val in response.headers.multi_items():
                if key.lower() not in omit:
                    self.send_header(key,val)
            self.send_header('Content-Length',str(len(response.content)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(response.content)
        except (httpx.HTTPError,ValueError):
            self.send_error(502)


def serve():
    crt=CERT_DIR/'cert.pem'
    if not crt.is_file():raise SystemExit('certificate not prepared')
    httpd=ThreadingHTTPServer(('127.0.0.1',18443),Handler)
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(crt),str(CERT_DIR/'key.pem'))
    httpd.socket=ctx.wrap_socket(httpd.socket,server_side=True)
    httpd.serve_forever()


if __name__=='__main__':
    import sys
    if len(sys.argv)!=2 or sys.argv[1] not in ('prepare','serve'):
        raise SystemExit('prepare | serve')
    if os.getenv('CI')!='true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP')!='I_ACCEPT_CI_ONLY':
        raise SystemExit('Disposable CI only')
    create_certificate() if sys.argv[1]=='prepare' else serve()
