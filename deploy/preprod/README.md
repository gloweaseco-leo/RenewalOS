# RenewalOS G1-I｜受保护预发环境决策包（尚未部署）

## 状态：NO-GO

本目录为**部署前验收契约**，不是可直接面向互联网启动的Compose。
应用`release_gate.assert_local_only`始终拒绝`staging`/`production`及`VERCEL`等云环境；
严禁利用反向代理绕过该限制。尚无已接入并经确认的企业IdP、客户授权、保密密钥或运维人员。

## 后续预发必须满足的条件

| 关口 | 验收证据 | 当前状态 |
| --- | --- | --- |
| 独立预发域名和TLS | 由受信CA签发的HTTPS、HSTS、Secure/HttpOnly Cookie、CSP及回调URL精确匹配 | 未具备 |
| 真实企业IdP | 固定issuer、实际metadata/JWKS、授权码+PKCE、强制MFA、定期密钥轮换与被吊销账号验证 | CI仅Keycloak合成演练 |
| 最小权限账户开通 | 管理员审批`issuer+sub`绑定，禁止按邮箱或IdP群组自动开通门店 | 代码实现，本地测试 |
| 访问边界 | VPN/ZTNA+身份认证，独立组织测试账号，审计拒绝和离职撤权 | 未部署 |
| 隔离数据库 | 专用低权限数据库角色、独立实例、TLS连接和自动迁移流水 | CI一次性PG |
| 密钥与灾备 | KMS、轮换、加密异地备份、恢复SOP、数据保留与删除 | CI一次性演练 |
| 浏览器验收 | 公共可达预发域名下真实浏览器E2E，无私人数据 | 仅GitHub本地环境 |
| 隐私与支付 | 未成年人隐私授权、真实支付来源和法律审查 | 未完成 |

只有经所有关口审批并采用独立的生产部署实现后，才能修改产品的NO-GO安全保护。
不得简单将`RENEWAL_DEPLOYMENT_TARGET=staging`设为允许值。

## 本轮真实Keycloak试验范围

在GitHub Actions**一次性**环境中启动Keycloak 26.8.0，容器HTTP仅绑定回环地址；
用一次性证书提供本地TLS网关；对预审签发者执行OIDC Discovery和JWKS核验；
用合成用户完成真实授权码与PKCE请求，**没有MFA的Token必须拒绝**；
重复授权码/State不得登录。Keycloak `start-dev`只能用于CI，不得在预发或生产沿用。
