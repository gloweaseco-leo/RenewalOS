# RenewalOS G1-D｜受控PostgreSQL业务工作台

状态：**仅本地合成数据开发版本，不可公网部署，不得导入真实客户资料。**

## 交付范围

- 将本地登录后的 `static/secure.html`、`static/secure.js` 完整切换到受认证的 `/api/v1/orgs/{org}/stores/{store}` PostgreSQL 业务路由；不再混用旧SQLite经营数据。
- 机构ID由操作者填写，门店从本地登录的授权清单选择；真实权限由后端会话和PG机构/门店成员关系二次校验，输入不是授权。
- 员工/经理共用机会详情视图：可解释机会基本事实、责任任务、跟进事件；**员工无法查询合同和资金详情**。
- 经理分配任务、登记合成续费合同、模拟付款和模拟退款；员工只在本人任务中进行跟进。
- 经理经营复盘仍是合成业务过程快照，`incremental_roi`保持NULL；独立对照组不产生定向任务。
- 前端同一未确认操作沿用事件ID重试，成功后删除当前草稿ID，尽可能降低网络不确定时的重复模拟收款风险。
- 新增 `GET /api/v1/orgs/{org_id}/stores/{store_id}/opportunities/{opportunity_id}`，在SQL层限制角色，绝不直接向员工查询合同资金表；不存在/未授权案件统一返回404。

## 如何验证

1. `python -m pytest -q` 运行SQLite与静态回归；本机无PostgreSQL时PG测试标记为跳过（不能称为PG通过）。
2. `node --check static/secure.js` 确认浏览器脚本语法。
3. 本地 `python scripts/dom_smoke_g1d.py` 使用Chromium + **mock API**，检查从登录到模拟退款的DOM交互。这不是HTTP实网端到端验收。
4. GitHub Actions里由 disposable PostgreSQL 16应用001/002迁移，复用G1-C的实体数据测试，并验证经理/员工详情端点、资金脱敏、门店串读拒绝。

## 仍未解决的真实商业产品阻断

1. G1-A本地账号、会话与授权表仍然存放在SQLite；尚未实现统一PG/OIDC身份系统。
2. 缺少生产可用的用户管理、租户注册、权限生命周期、CSRF/会话治理和个人信息保护。
3. 尚未接入真实支付平台、合同签约服务、课程系统回写及验真。
4. PostgreSQL测试数据只在一次性数据库中运行；不允许直接迁移或访问奥冠客户数据。
5. 缺少真实HTTP浏览器E2E、生产备份恢复演练、审计日志治理和云端安全验证。

**合并策略**：开发PR基于G1-C；不得合并main或发布到现有Vercel地址。
