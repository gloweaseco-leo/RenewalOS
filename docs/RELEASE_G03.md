# RenewalOS G0.3 — 续费经营事实链与冻结队列

交付状态：**本地演示验证**，不代表生产可用、真实财务审计或AI因果增量已证实。奥冠合同是否签订与本产品独立。

## 具体交付

1. 新增 `renewal_contracts`：每份原课包只允许关联一份首期新续费合同，合同与来源课包所属学员必须一致，合同ID或源课包不能覆盖已记录事实。
2. 新增 `cash_events`：付款和退款独立记录；退款必须关联**同一合同的一笔明确付款**，不可超过该笔付款累计金额；完整批次校验失败会回滚。
3. 新增 `cohorts` 和 `renewal_cohort_members`：每门店每天可冻结一次当天观察队列，冻结资格取未来30天到期且已同意相关联系的课包，剔除冻结前已付款续费的课包。同一源课包不会重复入队。家庭实验组记录在冻结时快照并保持不变。
4. 新增 `GET /api/cycles/{package_id}/timeline`：按事件显示原课包、冻结、员工跟进、合同、付款及退款。旧版无合同关联的 `renewals` 以 `legacy_*` 标识，不与新账本直接混算。
5. `GET /api/cohorts` 报告分实验组显示冻结家庭、已付款家庭、窗口内实际付款及其原单退款。**仍不计算因果增量、经营利润和ROI**。
6. `POST /api/cohorts/freeze` 只允许当天冻结，阻止拿今日数据倒推历史入组；重复请求只返回同一冻结队列，不重写组别。
7. 首页和经营验证页增加冻结、跟进事件及新资金口径展示；CSV导入扩展新合同和现金事件。

## CSV顺序

- 学员：`learner_id,family_id,guardian_alias,store_id,contact_consent`
- 课包：`package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cny`
- 考勤：`event_id,learner_id,session_date,status`
- G0.2遗留数据（若有）：`renewal_id,learner_id,source_package_id,paid_on,amount_cny,status`
- G0.3新续费合同：`contract_id,learner_id,source_package_id,signed_on,contracted_amount_cny`
- G0.3现金事件：`event_id,contract_id,event_on,kind,amount_cny,refund_of`

示例现金流水（先付款后退款；`refund_of` 填付款事件ID）：

```csv
event_id,contract_id,event_on,kind,amount_cny,refund_of
P1001,C1001,2026-10-17,payment,2800.00,
R1001,C1001,2026-10-18,refund,300.00,P1001
```

其中日期仅为格式示例，不是奥冠交易数据。新合同的 `contracted_amount_cny` 是合同金额，**不能当作到账款项**。所有金额以整数分存储。

## 观察期口径

- 冻结当日起45日为支付观察窗口；另留14日退款观察窗口。
- 只有支付日期处于观察期内且截至查询时已发生的现金事件计入队列付款。
- 退款按明确关联的付款冲减，即使退款发生在窗口之后也冲减对应支付，报告会随新增退款变动。
- 分母按冻结当时合格家庭固定，不因续费、缺课、退款或随后的数据更新重新筛选。
- 当前输出为描述性结果。跨组因果效果还缺样本平衡检验、统计区间、完整增量成本和销售流程一致性。成熟期结束只代表时间条件满足，**不代表已经证明AI有效**。

## 验证

- `python -m pytest -q`：24项通过（15项G0.2回归 + 9项G0.3）。
- `node --check static/app.js`：通过。
- HTTP API 由 FastAPI TestClient 覆盖；禁止部署公网。

## 特别风险与后续阻断

- `renewal_contracts` MVP仅一原课包对应一个首期续费合同；复杂续费拆单、升级课包、跨门店转课需要未来建模，不能硬导入。
- SQLite内没有生产身份认证、权限、访问审计、多租户隔离和依法处理学员数据的完整机制。严格禁止向本地演示服务导入真实可识别未成年人资料。
- G0.2旧 `renewals` 缺少新合同和退款原单引用，只保留兼容和单独事实展示；**不得与G0.3资金口径相加**。
- 课包剩余课时仍是导入快照，缺少消课事件账本，无法还原任意历史日权益状态，因此禁止历史补冻。
- 冻结后禁止更改原课包资格基线，但允许剩余课时变化；冻结后加入的新课包不会被回填到旧队列。
