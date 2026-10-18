# RenewalOS G1-A｜本地认证与门店隔离安全门

版本：`1.0.0a1`（G1工程建设第一批，**不是 G1 完成，也不是公网产品**）。

## 已交付

- `RENEWAL_RUNTIME_MODE=secure_local`：完全禁用 G0.8 所有未认证的演示业务 API（包括 CSV、重算、模拟付款、任务写入、模型测试），只开放健康、身份和**单门店只读**接口。
- 本地专用账户：PBKDF2-HMAC-SHA256 + 独立随机盐、390,000次迭代；随机一次性显示的Bearer Token，数据库只留Token的SHA-256散列；8小时到期、可退出撤销、停用账户即时失效。
- `access_memberships` 按账户+门店分别授权：`manager`可查看全店机会、任务及管理复盘；`staff`只能查看自己被分配的机会/任务；`auditor`是预留角色，当前不可浏览业务明细。
- 只读SQL在数据库查询阶段强制门店限制，越权返回403；缺少凭据/失效返回401；拒绝访问也持久化审计。
- 安全模式下的独立登录页面：内存Bearer，不使用LocalStorage，不输出 HTML 非可信字符串。
- 初始账号须通过命令行人工创建；不得通过HTTP自动注册。
- 未识别的运行模式拒绝启动；公共Host和非回环来源地址均拒绝。**不能依赖Host头防伪造来代替127.0.0.1绑定。**

## 可复现的本地预览

> 仅使用不含个人信息的合成数据、单独的SQLite文件。请先运行 `pip install -e '.[test]'`。

```bash
export RENEWAL_RUNTIME_MODE=secure_local
export RENEWAL_DB_PATH=/tmp/renewalos-g1a-synthetic.sqlite
python -m renewalos.seed_secure_demo --confirm-synthetic-only
python -m renewalos.provision demo_manager --store DEMO-STORE --role manager
python -m uvicorn renewalos.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell请用 `$env:RENEWAL_RUNTIME_MODE="secure_local"` 和 `$env:RENEWAL_DB_PATH="..."` 设置变量；在本机浏览器打开 http://127.0.0.1:8000 ，输入刚刚人工创建的账户与密码。账号初始化脚本用 `getpass()`，避免密码出现在命令行历史。

可检查：`GET /api/health`、`POST /api/auth/login`、`GET /api/v1/me`、`GET /api/v1/stores/DEMO-STORE/opportunities`、`.../tasks`、`.../management`、`POST /api/auth/logout`。

## 尚未交付 / 必须保持关闭

- 生产级身份源（OIDC/SSO、MFA、重置、锁定/限流）、租户组织与真正的 `user_id` 任务分配迁移、管理权限的完整工作流写入。
- PostgreSQL持久化、机构级（org/tenant）数据模型与RLS、并发下的授权事务边界、加密和备份、文件导入隔离、数据留存与删除。
- 真实客户和未成年人个人信息的授权处理、安全审查、日志脱敏、部署拓扑、域名/TLS/WAF、生产运维监控。
- 真实合同与支付网关核验。现有G0.8的旧接口在安全模式**全部不可调用**。

**生产放行标准：** 所有业务读写均使用统一鉴权与租户约束；通过跨租户/越权/并发/数据迁移/灾备测试，才可讨论公网部署。详见 `ADR_G1_DATA_ARCHITECTURE.md`。
