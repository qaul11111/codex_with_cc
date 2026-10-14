# GPT-6 Astra 下的插件使用指南

Astra 主线程负责需求、决策、任务边界和聚焦验收，保持上下文简洁。简单、位置明确、
低风险的小任务可以自己做；需要大量探索、反复试错、批量或复杂实现的工作交给子代理。
紧密耦合的大任务由一个工作代理从调查做到修复和验证，独立部分才并行。
不按固定行数、文件数或分钟数机械分流，也不为省调度时间把复杂工作搬回主线程。

## 按任务选择

| 场景 | 执行方式 | 验收方式 |
| --- | --- | --- |
| 简单、位置明确、低风险的小任务 | 主线程直接完成 | 检查结果与必要验证 |
| 需要探索、试错或耦合较强的实质性修改 | 一个工作代理端到端完成 | standard，主线程聚焦审查 |
| 相互独立的调查、批量或较大实现 | 按实际容量并行派工 | standard，真实执行证据 |
| 用户要求独立审查，或风险需要独立把关 | strict | 绑定当前实现的 spec、quality、final-verifier |

工作代理负责仓库探索、实现、测试和局部修复；主线程不接收完整日志和重复调查过程。
每个任务保留六个合同字段，但内容简短具体；不要把调查、实现、测试强制分成三个代理。
报告保留八个字段，作为简短结果卡展示变更路径、检查结果、风险和证据链接。
主线程据此按需读取相关 diff 与证据，并保留最终判断。

## 执行路由

保留用户当前选定的 Claude 供应商及显式路由。未要求 Claude 或供应商专属能力时，
可以选择 codex-native。Claude 工作优先受支持的 `claude-process`：Astra 主线程
直接调用准备好的固定启动器，Claude 工作进程负责探索、实现、测试和修复，没有纯
Codex 模型转交层，也不是 Codex 子线程。保留旧版 `claude-code` 的 carrier 兼容链，
其中 carrier 只启动和转交结果。省去一层调用不是已测得的提速或省钱承诺。
安全的 Claude 会话复用仅限当前 runtime 支持的会话与锁机制；已经结束的 Codex 宿主尝试不能复用。

| 用途 | 默认模型 | 推理强度 |
| --- | --- | --- |
| 主线程 | 保留宿主当前设置 | 保留宿主当前设置 |
| Claude process 启动 | 无模型载体 | 无 carrier effort |
| 旧版 Claude 启动与结果转交 | gpt-5.6-luna | low |
| Claude Code 实际执行 | sonnet 别名 | 按任务 WorkerEffort；未指定时按角色旧默认值 |
| Codex 原生子任务 | gpt-6-astra | high |

`sonnet` 是请求别名，实际模型以执行记录的 `actualModels` 为准。主线程按任务复杂度和
能力选择模型、推理强度及预算，覆盖值记录 `DecisionReason`，先检查当时宿主/供应商支持。
不修改全局供应商配置，不用静默切换 Claude 到 native 来宣称变快或省钱。

## 使用方式

- “这个小改动位置明确，你直接修改并验证。”
- “这个问题需要探索，用当前 Claude 供应商让一个代理从定位做到修复和测试，你负责验收。”
- “允许用 native，把两个独立模块并行实现，主线程只接收结果卡并审查关键 diff。”
- “这次权限变更用 strict，独立审查绑定当前实现。”

明确的用户选择优先；仅讨论插件或代理不启动执行。

命令使用已安装缓存的 `skills/codex-with-cc/scripts/runtime.py`，完整参数见
[命令指南](skills/codex-with-cc/references/astra-workflows.md)。普通准备不需要预读完整旧版合同。

1. `configure-workflow` 固定项目、模式和默认模型，按真实可用容量设置 `-MaxParallel`；按路由运行 `configure-lifecycle`。process 使用 `process-exit`，不要求 spawn/close 工具。
2. `prepare-task -Admit` 可合并准备与准入。尚未就绪的依赖任务可先准备，再用 `ready-tasks`、`admit-task` 逐批准入；准入失败保留排队计划，不返回启动载荷。
3. process 准备时指定 `-Backend claude-process -AllowedCommandsFile <commands.json> -ExecutionTimeoutSeconds 900`；命令文件使用精确 argv，并固定相关脚本的哈希。主线程在返回的目录执行无参数固定启动器。子线程路由才使用返回的模型、effort、task_name、WorkflowPlan、fork_turns 并登记真实 agent id。
4. process 验证原始主线程身份、计划、供应商、命令授权和实际启动/退出证据，不写虚假子线程记录。旧版 Claude carrier 执行固定启动器；native 的 `record-native-run -Settle` 可合并结果导入和终止登记，仅适用于 terminal-evidence；strict-close 仍需真实关闭。
5. `review-packet` 生成只读、有界、确定性的审查卡，标注截断并链接原始证据。`advisoryOnly` 表示它不能替代验收。
6. 工作代理自行选取、运行测试并修复。主线程调用一次确定性的 `run-checks` 验收关卡，再 `record-main-review`、`verify-workflow`；普通工作代理日志不会自动导入成验收证据。strict 另需独立审查。

准备/准入及导入/终止登记的四次调用可合成两次，不代表总耗时减半。必需验证通过后，
仅在覆盖输入或执行变化、出现失败或未决风险时补充检查，不为“主线程再做一次”而重复测试。
每次重试保留历史记录，创建新宿主尝试；无用的未派发计划用 `cancel-prepared-task` 正式撤回。

## 证据与当前边界

- 原生结果收集依赖本地原始 JSONL 中的身份、模型、终止事件和最终答复。云任务或原始日志不可读的宿主暂不支持；离线测试通过不等于真实模型或新宿主验收。
- process 目前支持本地 POSIX 宿主，使用真实 PID、开始/退出和原始产物；超时取消有界，不把超时或中断报告恢复为成功。命令授权不是通用 shell 放行；新增命令或固定输入变化需要新计划。
- 子线程路由在宿主没有关闭接口时核实终止证据并保留 `closeStatus=unsupported`；中断不是关闭。process 不使用线程关闭措辞。未执行计划、未解决生命周期、失败或缺少证据仍阻止验收。
- 默认全仓输入快照；完整声明共享代码、构建配置和依赖后才可范围化。被忽略的依赖和环境仍需适当集成验证。
- `DONE_WITH_CONCERNS` 可由主线程用 `DecisionsFile` 逐项记录已解决、接受风险或不适用；不能放行失败或缺失验证。
- 用量区分主线程、carrier、执行模型、重试和返工；缺失值为 null，CLI/供应商估算不是账单。`MaxBudgetUsd` 不是跨供应商或工作流总预算保证。
- 安装更新后开始新任务以加载新技能和 hook；本次活动任务可能仍带旧提示。

2026-09-05 基准中的 63–75 秒额外调度时间只属于旧环境测量。该报告建议把难定位或耦合
工作直接留给主线程的结论已由本指南替代；仍允许简单小任务直做。当前没有新的同题真实
模型对照结果来证明提速或节省费用。优先改进和测量标准见
[上下文与吞吐设计](CONTEXT-CLEAN-THROUGHPUT.md)。
