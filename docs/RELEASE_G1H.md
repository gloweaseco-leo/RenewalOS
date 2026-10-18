# G1-H｜供应商中立OIDC身份链（仅本地合成测试）

## 业务与安全边界

- 采用授权码交换 + **S256 PKCE**，nonce和加签ID Token；签发者、受众、时效、签名算法严格验证；阻止HS256、伪造`kid`、无MFA声明和来自其他issuer的令牌。
- 登录发起时生成随机`state`，SHA256哈希入库且五分钟到期；双提交浏览器HttpOnly SameSite=Lax Cookie绑定，完成时原子删除。重放或异浏览器提交失败。密码登录在`oidc`模式关闭。
- 用户只通过管理员预置的 `(issuer,subject)→user_id` 映射进入原PostgreSQL用户与机构/门店授权模型。**不根据email、邮箱认证、姓名或令牌组声明赋权**；用户禁用仍阻断业务访问。身份会话使用数据库可撤销哈希Token，最长4小时。
- 仍只能监听本机回环地址，`assert_local_only`始终阻止`production/staging/VERCEL`等公网目标。**不得把通过本地OIDC测试解释为正式SSO放行。**
- OIDC客户端端点由管理员事先审查并配置，必须全部HTTPS且与issuer同域；无任意URL参数、无动态发现时用户指定URL、无自动预配账号。认证码经浏览器`/`回调，页面立即清理地址栏参数。正式公网部署需要再选择托管供应商、HTTPS回调、审计日志脱敏、生产Cookie策略与会话模型。

## 新增文件及验收

- `renewalos/oidc.py`：供应商中立PKCE+state、Token签名与MFA、人工映射以及数据库会话。
- `migrations/postgres/004_oidc_local.sql`：OIDC映射、一次性流表和必要的最小权限；变更审计事件检查约束。
- `scripts/pg_apply_g1h.py`：硬限定一次性CI数据库迁移；不支持直接迁移真实客户数据库。
- `/api/auth/methods`、`/api/auth/oidc/start`、`/api/auth/oidc/complete`：仅本地模式可用；工作台在OIDC配置下显示企业登录入口。
- `tests/test_g1h_oidc.py`：RSA签名/MFA负例、未绑定用户拒绝、浏览器Cookie绑定、重放、管理员映射与本地禁用密码登录。
- CI PostgreSQL16执行001-004迁移、G1-H真实数据库认证映射测试和已有G1-F浏览器业务流程回归。所有外部IDP交互由测试用模拟HTTP Transport提供，**并未连接任何真正的企业身份供应商**。

## 尚未满足的生产条件

1. 企业身份供应商选型、真实元数据、供应商签名密钥轮换、MFA策略和真实账号联调；SSO/SCIM入职离职、权限审批与审计。
2. 正式HTTPS、可信反向代理、Secure Cookie/BFF会话、OIDC回调中认证码访问日志脱敏、防撞库/速率限制、多实例事务容量。
3. 秘钥管理/KMS、异地加密备份与实际恢复、运维告警及灾难切换。
4. 未成年人客户资料的合法授权、最小化采集、保留和删除制度；真实支付/退款来源对账。

`public_release=NO_GO` 仍为**强制**，不得合并`main`或发布现有Vercel。
