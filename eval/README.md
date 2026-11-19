# dev-task-splitter 评测集

本目录是测试工程师准备的 **v1 评测材料**，用于在实现（Python + Streamlit + DeepSeek）之后衡量「杂乱需求/bug → 要做的任务、要测的点、要问清楚的问题」的质量。

它**不属于** GitHub 仓库当前内容的拷贝。评测时查看的公开仓库 https://github.com/zzhqqa478850-lang/dev-task-splitter 仍处于初始提交：只有标题为 `# dev-task-splitter` 的 `README.md`，无应用代码、无 prompt、无 schema、无测试、无 open PR/issue。因此本评测集的输出格式对齐的是架构草案 v1 中的 `SplitResult` JSON（见 `/workspace/dev-task-splitter-arch-v1.md`），而不是仓库里尚不存在的实现。草案若与日后合并的 `splitter/schema.py` 不一致，应改解析器与本说明，不要假装仓库里已经有 schema。

## 文件

| 路径 | 说明 |
|---|---|
| [`cases.jsonl`](cases.jsonl) | 全量 20 条，UTF-8，每行一条 JSON |
| [`rubric.md`](rubric.md) | 全量评测的维度、细则与通过线 |
| [`samples/`](samples/) | 产品经理定稿的 10 条人工冒烟样例（需求 5 + bug 反馈 5，其中 S04 故意模糊）、额外注入用例 X01、评审表与异常用例 |
| [`samples/review_sheet.md`](samples/review_sheet.md) | 评审表（同内容还有 `samples/review_sheet.csv`） |
| [`samples/edge_cases/`](samples/edge_cases/) | 空输入、3000/3001 字符边界、超长、无 API key、401/403、超时、429、5xx/网络错误、JSON 解析失败，不计入 8/10 |

## `cases.jsonl` 字段

每条均含：

| 字段 | 含义 |
|---|---|
| `id` | `C01`–`C20` |
| `category` | 评测设计类别（清晰需求、模糊需求、超长需求、信息不足、中英混杂、bug报告、多需求混合、自相矛盾、极短输入、非需求或注入） |
| `input_type` | 架构枚举金标：`feature` / `bug` / `mixed` / `unclear` / `other` |
| `accepted_input_types` | 同样可接受的取值（默认只有金标；目前极短输入 C17、C18 允许 bug / unclear，C10、C13 允许 feature / mixed） |
| `input` | 用户原文，评测时只把这一段交给系统 |
| `expected_tasks` | 关键任务要点（不是模型必须一字不差输出的标题） |
| `expected_test_points` | 应覆盖的测试要点，含边界 |
| `expected_questions` | 应追问的缺失或冲突信息 |
| `notes` | 易漏点、幻觉禁区、与 schema 的对齐说明 |

`expected_*` 用于要点覆盖，不要做字符串全等。模型侧仍应输出完整 `SplitResult`（含 id、priority、`task_ids` 等）。

### 类别分布（20 条）

| category | 条数 | id | 标注的 input_type |
|---|---:|---|---|
| 清晰需求 | 2 | C01, C02 | feature, feature |
| 模糊需求 | 2 | C03, C04 | unclear, unclear（另须有 `clarification` 任务且 questions 非空） |
| 超长需求 | 2 | C05, C06 | feature, feature（按 `len(input.strip())`：C05 从 3098 删去两段闲聊缩到 2981，C06 为 2984，都 ≤3000，应正常拆解；超限拒绝见 `samples/edge_cases/` 的 E03、E08） |
| 信息不足 | 2 | C07, C08 | feature, feature |
| 中英混杂 | 2 | C09, C10 | feature；**C10 为 mixed**（也接受 feature：「webhook 老丢事件」没有具体现象，属边界） |
| bug报告 | 2 | C11, C12 | bug, bug |
| 多需求混合 | 2 | C13, C14 | feature（也接受 mixed，对应 samples/S02）；**C14 为 mixed**（多项功能 + 隐私协议 404） |
| 自相矛盾 | 2 | C15, C16 | feature, feature |
| 极短输入 | 2 | C17, C18 | bug, bug（也接受 unclear） |
| 非需求或注入 | 2 | C19, C20 | unclear, unclear（两条去掉注入后都没有真实需求，只接受 unclear，other 不算通过） |

`input_type` 金标合计：feature 10，bug 4，mixed 2，unclear 4（另有 C13 也接受 mixed，C10 也接受 feature，C17、C18 也接受 unclear）。

`mixed` 判定：既有至少一项新功能或改动需求，又有至少一项「现有功能行为不符合预期」的具体现象时才判 `mixed`；需求矛盾、模糊抱怨、体验建议不算 bug。详见 `rubric.md` 3.7。

条数上限：输出 `tasks` ≤ 10、`test_points` ≤ 20、`questions` ≤ 8、`steps` ≤ 5。`expected_*` 是要点，一条输出任务覆盖多个要点也算覆盖，合并不算漏。各条期望条数都在上限内（expected_tasks 最多 9 条、expected_test_points 最多 10 条、expected_questions 最多 4 条）。

## 与架构输出对齐的用法

成功时的目标结构见 `rubric.md` 第 1 节。界面应能展示三块，并可下载 JSON / Markdown。Markdown 只是渲染，**评分以 JSON 能否按 `SplitResult` 解析为准**。

建议的评测步骤：

### 手工

1. 从 `cases.jsonl` 取出一条的 `input`，原样贴进应用（或以后的 CLI）。
2. 保存完整 JSON、实际耗时（秒）和重试次数。
3. 按 `rubric.md` 打分，对照 `expected_*` 与 `notes`。
4. 需要稳定性时，同一条连跑 3 次。
5. 产品冒烟则改用 `samples/S01`–`S10`，只填 [`samples/review_sheet.md`](samples/review_sheet.md)。

### 脚本（实现后自行编写，本目录不绑定尚不存在的接口）

仓库还没有可调用的模块。待 `splitter.agent.run(raw_text) -> SplitResult` 可用后，建议：

1. 读取 `cases.jsonl`；
2. 对每条调用 `run(input)`，捕获异常、耗时与原始文本；
3. 先做 pydantic / 业务引用校验，再按要点做覆盖（可用人工，或以后加 LLM 辅助打分）；
4. 不要把 API key 写入本目录或提交到 git。

异常路径（无 key、401/403、超时、429、5xx/网络错误、非法 JSON、长度边界）用 `samples/edge_cases/`，不要和 20 条正/风险样例混在一张「内容质量」表里。

## 产品冒烟（10 条）与全量评测的关系

产品经理定稿：

- `samples/` 正好 10 条：需求 5、bug 反馈 5，内容为真实杂乱风格，其中 S04 故意写模糊；另有额外注入用例 X01，不计入 8/10；
- 不触发重试时，每条 60 秒内出结果；单次调用超时默认 60 秒（可配置）；所有重试都只有 1 次；
- 人工评审至少 8/10 合格；
- 合格 = 任务、测试点各至少 1 条且不串类；问题默认可以为空，`input_type == "unclear"` 时必须非空；S04 还须满足 `input_type == "unclear"`、至少 1 个 `clarification` 任务、questions 非空。

这是上线前的冒烟门槛。全量 20 条还覆盖注入、极短、超长、信息不足等，并用 `rubric.md` 看漏任务、幻觉和鲁棒性。两套都要通过，才能认为质量可接受。

## 已知限制

- 全量集的期望是要点，不是标准答案 JSON，尤其是任务拆多细会有合理差异。
- 规则依据：架构文档 v1 文末变更记录（2026-11-20）。长度按去首尾空白后的字符数计，≤3000 放行，3001 起拒绝且不截断；`questions` 默认可以为空，`unclear` 时必须非空。
- 注入输入的 `input_type`（架构师定）：注入类按去掉注入指令后的真实内容判：只有注入、没有真实需求的，input_type 定死为 `unclear`（须有「重新提供需求」类 `clarification` 元任务，`questions` 非空）；夹带真实需求或 bug 的，按真实内容填 `feature` / `bug` / `mixed`。`other` 对注入类不算通过。
- 除 429 的「请求太频繁（已重试 1 次），请稍后再试。」外，错误文案都以实现为准。
