# samples（手动回归样例）

本目录用于产品经理定稿的 v1 验收：把样例原文贴进应用（实现后为 Streamlit 输入框），检查是否在时限内返回、三块输出是否合格。

> 仓库当前仍只有初始 `README.md`，尚无应用代码。本目录是预先准备的验收材料，供实现后使用。输出格式以架构草案 v1 的 `SplitResult` JSON 为准（字段含 `input_type`、`summary`、`understanding`、`tasks`、`test_points`、`questions`、`self_check`）。界面渲染「要做的任务 / 要测的点 / 要问清楚的问题」三块，并可下载 JSON / Markdown。

更细的质量评分（漏任务、边界覆盖、幻觉、注入鲁棒性等）见评测集 [`../rubric.md`](../rubric.md) 与 [`../cases.jsonl`](../cases.jsonl)。**本目录的 8/10 是冒烟验收，不能代替全量评测。**

## 验收标准（10 条正样）

1. 正好 10 条真实风格样例：**需求 5 条 + bug 反馈 5 条**（异常用例另行放置，不计入这 10 条）。
2. 每条须在 **30 秒内**出结果。
3. 人工评审至少 **8/10 合格**。
4. **合格**定义（须同时满足）：
   - `tasks`（要做的任务）非空；
   - `test_points`（要测的点）非空；
   - `questions`（待澄清问题）非空；
   - **不串类**：测试点不写进任务、问题不写进测试点、任务不是问题清单，三块职责分离；
   - 耗时 ≤ 30 秒。

说明：架构 v1 的 JSON schema 里 `tasks`、`test_points` 已要求 `minItems: 1`，但 `questions` **未**要求最少 1 条。产品验收明确要求问题块也非空。下列 10 条都足够杂乱，预期应当产出待澄清问题。若实现只按 schema 允许空 `questions`，本验收仍按「问题非空」判定——如需改校验规则，请产品经理与开发确认。

`input_type` 枚举按架构文档：`feature` / `bug` / `mixed` / `other`。本 10 条只使用 `feature` 与 `bug`（与「5 需求 + 5 bug」对齐）。`mixed`、`other` 以及更极端的模糊/注入用例在全量评测集里，不计入本次 8/10。

## 如何使用

1. 实现并本地启动应用后，按 `S01` 到 `S10` 依次将对应 `.txt` **全文**粘贴到输入框并提交。
2. 用秒表或界面耗时记录是否 ≤ 30 秒；超时记不合格。
3. 查看三块是否非空、是否串类；`input_type` 是否与下表一致（分类错误记入备注，是否单独判不合格由评审约定，默认不改变「三块非空 + 不串类 + 时效」的合格定义）。
4. 在 [`review_sheet.md`](review_sheet.md) 或 [`review_sheet.csv`](review_sheet.csv) 逐行填写，底部汇总合格数，并判断是否达到 8/10。
5. 再按 [`edge_cases/README.md`](edge_cases/README.md) 跑异常用例（不计入 8/10）。

机器可读索引：[`index.json`](index.json)。

## 10 条样例

| 编号 | 文件 | 类型 | input_type | 标题 | 字符数 | 来源 |
|---|---|---|---|---|---:|---|
| S01 | `S01_feature_coupon_redemption.txt` | 需求 | `feature` | checkout 优惠码兑换（中英混杂） | 622 | C09 |
| S02 | `S02_feature_multi_requests.txt` | 需求 | `feature` | 暗黑模式/发票/定时推送/关于页改地址等多需求混杂 | 253 | C13 |
| S03 | `S03_feature_contradictory_search.txt` | 需求 | `feature` | 搜索排序/分页/游客访问规则自相矛盾 | 170 | C15 |
| S04 | `S04_feature_contradictory_notifications.txt` | 需求 | `feature` | 推送/短信免打扰规则自相矛盾 | 262 | C16 |
| S05 | `S05_feature_points_mall_messy.txt` | 需求 | `feature` | 积分商城第一期（群聊纪要，含闲聊） | 1072 | C05（压缩至 3000 字以内，完整超长版见 edge_cases） |
| S06 | `S06_bug_coupon_list_500.txt` | bug反馈 | `bug` | 我的优惠券页 500（expire_at 为空） | 742 | C11 |
| S07 | `S07_bug_login_502_redis.txt` | bug反馈 | `bug` | 登录 502（Redis 写 session 失败） | 1042 | C12 |
| S08 | `S08_bug_payment_webhook_lock.txt` | bug反馈 | `bug` | 已付款订单仍待支付（乐观锁与支付宝字段） | 1319 | 本目录新写 |
| S09 | `S09_bug_checkout_white_screen.txt` | bug反馈 | `bug` | 结算页白屏（gift item.price 为 null） | 978 | 部分背景可对照 C09，本条为独立缺陷 |
| S10 | `S10_bug_login_sms_messy.txt` | bug反馈 | `bug` | 登录验证码杂乱反馈（收不到/错误/端差异/疑似 4 位码） | 304 | 本目录新写 |

以上 10 条正文均在约 3000 字上限之内，便于作为「应能成功拆解」的正样。约 3000 字与明显超限文本放在 `edge_cases/`。

## 合格与串类的判断提示

- **非空**：对应数组至少 1 项，且不是只有空白/「无」「暂无」这类空话；元任务（如「复现并定位」「先澄清冲突再实现」）算非空，空数组不算。
- **不串类**：
  - 任务：可执行的工作项（动词开头，如「实现…」「修复…」「复现并定位…」），不是测试步骤，也不是向用户提出的问题；
  - 测试点：场景、边界、期望结果，不是开发任务列表，也不是待确认问题；
  - 问题：向用户/产品追问的缺失或冲突信息，不是把任务或用例再抄一遍。
- bug 类样例按架构约定，第一个任务宜为「复现并定位」。这作为备注观察项，是否纳入 8/10 合格定义以评审时约定为准（默认不强制，但应在备注记录）。

## 与全量评测集的关系

| 材料 | 位置 | 用途 |
|---|---|---|
| 本目录 10 条 + 评审表 | `samples/` | 实现后的人工冒烟验收（30 秒、8/10、三块非空且不串类） |
| 异常用例 | `samples/edge_cases/` | 空输入、超长、无 key、超时、JSON 失败等，不计入 8/10 |
| 全量评测集 | `cases.jsonl`（20 条，含 `input_type`） | 覆盖模糊、超长、信息不足、中英混杂、多需求、自相矛盾、极短、注入等 |
| 评分细则 | `rubric.md` | 任务完整性、边界、追问、格式稳定性、幻觉、鲁棒性 |
