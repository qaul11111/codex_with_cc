# 插件真实模型测试记录 · 2026-09-05

已通过当前安装的 codex-with-cc 插件完成两次真实 Kimi 调用。两次都能修复题目中的主要逻辑错误，但第二次在 Python 类型兼容上增加了题目没有要求的限制。当前结果支持“交给 Kimi 处理范围明确、可自动验收的工作，再由 Astra 复核”；尚不能证明这条链路比 Astra 直接处理更便宜。

本次沿用 CC Switch 当前启用的 Kimi，未切换或调用 DeepSeek，未修改 Claude 配置或插件业务代码。测试产物保存在本地。

**实际运行配置**

插件版本为 `1.2.0+codex.20260905013111`。链路为 Astra 主任务 → 两个 Astra/xhigh 调度子代理 → 固定 launcher → Claude Code CLI → Kimi Code。当前任务仍加载旧的路由约束，因此本轮没有验证 Luna 调度或原生执行路线。

Claude Code 使用 Kimi 的 Anthropic 兼容端点；插件请求的 `sonnet` 在本机映射为 `k3-256k`。两次响应均报告实际模型 `k3-256k`、速度档位 `standard`。虽然配置中另有 `kimi-for-coding-highspeed`，这两次不能算高速版测试。

每次 CLI 估算预算上限 $2、执行超时 240 秒、自动重试次数 0。两个独立会话并行执行，均首次完成，无传输重试、无模型返工。

**效果与耗时**

测试是一项只读 Python 代码审查：修复带有版本覆盖、撤销、时间边界、排序、输入校验和不修改输入等要求的任务选择函数。模型在报告中提供候选函数并运行自己的内存测试；主任务再提取原始候选代码进行验收。

| 真实调用 | 预先固定的用例 | 复核补充用例 | Kimi 执行耗时 | 含调度子代理的耗时 | CLI 美元估算 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Kimi 第一次 | 536/536 | 2/2 | 143.92 秒 | 219.02 秒 | $0.297835 |
| Kimi 第二次 | 536/536 | 0/2 | 123.01 秒 | 185.56 秒 | $0.228675 |

固定测试在派工前冻结：36 个手写用例、500 个确定性随机用例，随机种子为 `20260905`。两个任务文件内容完全相同，输入、参考实现和固定测试的 SHA-256 已核验未改变。固定测试结果与复核后新增的结果分别记录，没有回改初始成绩。

第二次候选函数使用 `type(row) is dict` 和 `type(id) is str`，拒绝了合法的 dict/str 子类。题目仅要求整数必须是精确类型。因此两个补充用例分别验证字典子类和字符串子类：第一次均通过，第二次均失败。第二份报告虽然提到了这种限制，却将其解释为符合要求，说明自述风险不能代替主任务的判断。

文字分析也有局部误判，例如将“未知 state 会被接受”列为原代码缺陷，而原代码已有 pending 状态过滤。主要修复思路可用，报告中的每条判断仍需核对。

Astra 主任务在派工前写的参考候选通过 536 个固定用例和 2 个补充用例，但它同时参与了题目与测试设计，不能作为独立、盲测的模型对照，也没有可单独归因的推理耗时或费用。该测试仅覆盖一类小型纯函数任务，两次调用不足以推断大型仓库修改、多文件协作或长期稳定性。

**Token 与费用边界**

| 统计项 | Kimi 第一次 | Kimi 第二次 | 合计 |
| --- | ---: | ---: | ---: |
| 未缓存输入 Token | 25,896 | 8,522 | 34,418 |
| 缓存读取 Token | 66,560 | 110,080 | 176,640 |
| 输出 Token | 5,403 | 5,241 | 10,644 |
| Kimi Token 总量 | 97,859 | 123,843 | 221,702 |
| CLI 美元估算 | $0.297835 | $0.228675 | **$0.526510** |

输出 Token 已包含响应中报告的 thinking 用量，不重复相加。总 Token 是多轮请求累计值。

**$0.526510 是 Claude Code CLI 报告的两次 worker 估算值，不是已确认扣款，也不包含 Codex 调度和主任务开销。** Kimi Code 使用会员订阅权益，与 Kimi 开放平台的按量计费不同；兼容客户端报告的美元数字不能直接当作会员账单。[Kimi 官方会员说明](https://www.kimi.com/en/help/kimi-code/membership-guide)

2026-09-05 09:49:42（北京时间）的 Kimi 账户只读查询显示：主额度池剩余 63/100，五小时窗口剩余 99/100，账户级别 `LEVEL_ADVANCED`。接口未提供逐请求金额，且本轮没有测试前的 Kimi 额度快照，所以无法计算这两次消耗了多少会员额度；不能把主池已用 37/100 归因于本测试。

两个 Astra 调度子代理另外累计消耗 1,071,402 Token，其中输入 1,067,856、输出 3,546；输入中有 1,013,760 缓存 Token，未缓存输入为 54,096。约 94.9% 的输入来自缓存。这是多轮上下文累计，不能理解为单次输入超过一百万 Token，也不能按全部未缓存输入计价。这个调度开销值得优化，但单看 Token 数不能断言整体美元成本高于 Kimi 或 Astra 直接执行。

主任务在 09:39:38 至 09:48:13 的记录增量另有 2,706,742 Token，包含准备题目、协调、验收、查资料等工作，且日志存在当前输出延迟，不能当作单独的 Astra 解题消耗。之后整理报告的用量不在该快照中。Codex 账户周额度在前后查询均显示已用 56%；这是账户级、取整的读数，不能据此认为本测试没有消耗额度。全链路实际货币费用仍未知。

**对插件使用和下一步验证的影响**

1. 小型修复和紧密依赖当前上下文的工作，优先让 Astra 直接完成；本次调度链本身约多出 63–75 秒，尚未证明小任务值得派工。
2. Kimi 可用于范围明确、输入紧凑、验收标准可运行的批量工作。保留 Astra 最终检查，尤其检查模型自行扩展的类型限制、边界条件和没有证据的报告判断。
3. 下一轮成本验证应在重新加载插件约束的新任务中，对同样输入比较轻量调度与当前 Astra 调度，并记录每条链路的完整用量。当前本地安装虽支持轻量路线，本轮尚未实测其收益。
4. DeepSeek 可作为之后的同题对照；本轮没有调用，不能对它的效果或费用作结论。若继续测会员额度成本，应先保存前后额度快照，并注明账户同期其他使用可能造成干扰。

**执行与审计证据**

两次真实 worker 均退出码 0，原始输出完整，实际工具调用已核对。模型读取题目、运行内存测试并返回报告；未发现模型读取私有验收用例或写入源码。工作流验证通过，两个子代理均有原始宿主任务完成证据，已结算 2、待处理 0。当前宿主没有 close-agent 能力，因此关闭状态如实记录为 `unsupported`，没有宣称子代理已关闭。

工作流中的 `accepted` 是 researcher 报告与执行链路的验收，不等于候选代码没有缺陷；第二次候选的两个补充失败仍然保留。

- [题目及原始缺陷代码](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/input/problem.md)
- [第一次模型完整报告](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/artifacts/claude_20260905_094353_211_6c1c674c.md)
- [第二次模型完整报告](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/artifacts/claude_20260905_094408_036_1c0bcee0.md)
- [第一次固定测试成绩](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/judge/kimi1-score.json)；[第二次固定测试成绩](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/judge/kimi2-score.json)
- [复核补充测试结果](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/judge/supplement-results.json)
- [Token、耗时和 CLI 估算原始汇总](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/metrics.json)
- [Kimi 测试后额度快照](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/kimi-account-after.json)
- [实际工具执行记录](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/tool-evidence.json)
- [工作流与生命周期证据](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/codex_with_cc/benchmarks/20260905-093938/artifacts/workflow_real-kimi-20260905-093938.json)
