# RenewalOS G1-E | PostgreSQL 统一身份与真实 HTTP 验收

状态：**代码与测试工程，仍然只准本机 + 合成数据**。不是客户生产系统，也不是可以在 Vercel 公网直接部署的应用。

## 本期实现

- 新增 `003_pg_identity.sql`：`renewalos_auth.credentials`、会话、身份审计、严格限制的成员查询函数。
- 两条独立 PostgreSQL 连接：身份账户仅能处理密码摘要、会话、授权函数；业务账户保留 RLS 与机构/门店作用域，不能读取密码表。
- `RENEWAL_AUTH_BACKEND=postgres` 的安全本地模式下，启动不创建也不查询 SQLite 数据库；不具备两个独立 DSN 时拒绝启动。
- 登录返回 `org:store` 复合成员键；前端选择机构及门店时保持唯一作用域。同机构/跨机构同名门店不得串权。
- 原 `/api/v1/stores/{store}`（没有机构维度）在新身份模式直接禁用。新 API 由同一 PostgreSQL身份源授权，再对业务数据库作二次成员验证。
- CI 使用真实 PostgreSQL 16 + 独立身份/业务角色执行：逆向越权、会话撤销、身份停用、租户一致性及实际 Uvicorn TCP HTTP业务闭环。

## CI使用

CI自动执行以下迁移（**仅在一次性测试数据库中**）：

1. 001 tenant core
2. 业务数据库专用测试角色
3. 002 限制性业务迁移
4. 003 PostgreSQL 身份迁移
5. 身份数据库专用测试角色
6. pytest 和真实 Uvicorn HTTP E2E

身份角色不可查看 `renewalos.identity_users` 或其他机构的全局明细；业务角色不可读取密码散列与会话。生产应使用托管身份提供商及专门审查过的密钥管理体系，而不是将 CI 的测试角色或凭证用于生产。

## 运行边界

CI通过后可在受控本机测试：

```
RENEWAL_RUNTIME_MODE=secure_local
RENEWAL_AUTH_BACKEND=postgres
RENEWAL_PG_AUTH_DSN=postgresql://<dedicated_identity_user>@127.0.0.1:5432/<db>
RENEWAL_PG_APP_DSN=postgresql://<dedicated_business_user>@127.0.0.1:5432/<db>
python -m uvicorn renewalos.main:app --host 127.0.0.1 --port 8000
```

必须由数据库管理员完成机构、账户、角色与测试数据的合法初始化；**不能使用真实儿童身份、实际客户手机号或真实支付记录**。系统无完善的企业SSO/MFA、正式会话风控、邮件验证、导入授权、数据删除与备份恢复能力，禁止公网。

## 尚未完成的验收

- 使用真实浏览器和真实HTTP服务进行 UI 点击 E2E（已有模拟DOM验证与真实TCP API验证，二者不能混称）。
- 第三方 OIDC/SSO、MFA、HTTP 安全头、CSRF / 限流策略、审计归档、备份恢复、容灾。
- 正式机构入驻及管理员安全开户；授权真实交易集成与个人信息保护。
- Vercel适配与无状态运行验证；当前原型仍强制仅本机访问。

**没有任何AI带来增量续费的实证，也不展示虚构收益。**
