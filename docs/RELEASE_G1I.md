# RenewalOS G1-I｜真实IdP兼容性关口（仍不能上线）

新增 `renewalos/provider_probe.py` / `scripts/probe_provider_g1i.py`：

- 只读查询**预先审核的**`issuer/.well-known/openid-configuration`和JWKS；
- 拒绝issuer/authorization/token/jwks端点漂移、302跳转、缺少code+S256+RS256以及不合格RSA公钥；
- 只报告协议兼容性，不自动启用任何新的身份服务，不代表真实MFA有效或生产安全；
- 对真实IdP预检仅可在管理员批准后配置其端点和可信TLS证书；不自动读取用户资料。

GitHub新增Keycloak 26.8.0一次性认证服务、合成Realm、回环HTTPS代理、
真实授权码＋PKCE交换测试，验证**纯密码登录的IdP Token必须因无MFA被拒绝**；
这与之前的`httpx.MockTransport`测试不同，使用真实Keycloak签名密钥及HTTP端点。
使用Keycloak `start-dev`与一次性证书仅供隔离CI，严禁直接面向互联网。

`deploy/preprod/README.md`说明正式预发关口；本轮没有创建真实预发环境，
`RENEWAL_DEPLOYMENT_TARGET=staging/production`继续直接拒绝启动。
生产账号/真实学员/真实交易仍然禁止使用。

**G1-I已实现的只是IDP协议测试，不是实际企业MFA登录通过。**
真实供应商/企业账号、MFA正向联调、撤权、运维、HTTPS Secure会话与合规需要下一步单独完成。
