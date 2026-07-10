# Native Codex Agents 设计文档

## 目标

将 `codex_with_cc` fork 改造成一个 Native Codex Only 插件。在保留上游工作流纪律的同时，用 Codex 内置的 `spawn_agent`、`wait_agent`、`send_input` 和 `close_agent` 工具替换 Claude Code 委派层。

第一个版本采用硬 fork，不保留 Claude Code、CC Switch、DeepSeek 或 OpenAI 兼容的报告后端。

## 产品边界

该插件仍然是 Codex 的编排策略，而不是独立的代理守护进程。Skills 和 hooks 负责指导 Codex 主线程如何规划、派发、审查和验收任务。小型本地辅助程序只负责校验任务及工作流记录，不直接调用 Codex 内部的代理工具。

插件暂定名为 `codex-native-agents`。开发期间，GitHub 仓库可以继续使用 `codex_with_cc`，以便清晰保留 fork 关系和提交历史。是否重命名仓库不影响第一个可用版本的交付。

## 保留的契约

该 fork 保留以下上游设计：

- 每个用户请求对应一个 `WorkflowId`，每个委派任务对应一个稳定的 `TaskId`。
- Worker 角色包括：`planner`、`implementer`、`researcher`、`reviewer` 和 `final-verifier`。
- TaskFile 必须包含 `Goal`、`Allowed Scope`、`Forbidden Actions`、`Acceptance Criteria`、`Verification` 和 `Report Requirements`。
- Worker 必须输出结构化报告，包含 `Status`、`Role`、`Summary`、`Changed Files`、`Verification`、`Findings`、`Final Result` 和 `Risks Or Follow-ups`。
- 状态值包括：`DONE`、`DONE_WITH_CONCERNS`、`NEEDS_CONTEXT`、`BLOCKED` 和 `FAIL`。
- 并行可写任务必须声明明确且互不重叠的 Scope。
- 实现类工作流必须分别通过需求符合性审查、代码质量审查和最终验证门禁。
- 主线程负责架构、任务边界、返工决策、最终验收和对用户交付。

## 原生执行流程

1. 主线程先判断委派是否能真正帮助当前请求。
2. 主线程创建边界明确的 TaskFile，并在派发前完成校验。
3. 主线程为每个任务选择模型档位，然后使用 `fork_context: false` 调用原生 `spawn_agent`。
4. 相互独立的任务在同一轮中派发。只有 Scope 互不重叠时，可写任务才能并行执行。
5. 每个子代理读取自己的 TaskFile，遵守仓库规则，执行任务、完成验证，并返回结构化报告。
6. 主线程审查结果。需要返工时，使用 `send_input` 继续当前代理，或在确有必要时创建更高档位的新代理。
7. Implementer 的结果必须通过需求符合性审查、代码质量审查和最终验证后才能被接受。
8. 已完成的代理应及时关闭，并完成工作流记录。

每个子代理提示词都必须包含一个机器可读的任务信封，其中包括 `WorkflowId`、`TaskId`、`Role`、`TaskFile` 和 `Scope`。子代理不得继续创建嵌套代理，只有主线程可以派发任务。

## 模型路由

默认策略以单位用量对应的能力为优化目标，不要求所有子代理都继承最昂贵的父线程模型。

| 工作类型 | 默认模型 | 推理强度 |
| --- | --- | --- |
| 聚焦型调研、代码探索和机械性修改 | `gpt-5.6-luna` | `medium` |
| 常规实现和需求符合性审查 | `gpt-5.6-terra` | `medium` |
| 复杂实现和代码质量审查 | `gpt-5.6-terra` | `high` |
| 架构争议、高风险审查和最终验证 | `gpt-5.6-sol` | `high` |

模型路由是存储在机器可读契约中的软策略。Hook 不会仅仅因为配置的模型名不可用就硬性拒绝任务。如果 Codex 不再提供某个配置模型，派发逻辑应退回到继承父线程模型，并在工作流报告中记录这次降级。

失败或阻塞的任务最多允许提升一个模型档位，并且只能提升一次。重复失败后应把控制权交回主线程，不得开启无限重试。第一个版本不承诺精确的金额或额度倍率，因为当前原生工具只提供相对档位，并没有稳定公开的计费契约。

## 组件

### 核心 Skill

`codex-native-agents` 是用户明确提出子代理、委派或多代理请求时的统一入口。它负责判断什么时候值得委派，并让简单任务继续由主线程直接完成。

### 工作流 Skills

保留 planning、dispatching、worker、reviewing 和 finishing 等分阶段 skills，但全部围绕 Codex 原生工具重写。所有 skills 共享同一个 `contract.json`，不得重复维护模型规则或报告规则。

### Hooks

- `SessionStart` 注入精简后的原生工作流契约。
- `UserPromptSubmit` 只在出现委派触发词时补充该契约。
- `PreToolUse` 校验必要的任务信封元数据、禁止子代理递归，并拒绝 Scope 不安全的并行可写任务。

Hooks 只校验稳定的协议字段，不强制永久固定某个模型名，不调用 shell 委派脚本，也不会因为文档或代码里出现代理相关词汇就阻止主线程执行普通工作。

### 校验运行时

保留的 Python 运行时缩减为：

- TaskFile 校验；
- 工作流和任务记录更新；
- 结构化报告校验；
- Scope 重叠检测；
- 审查门禁和最终验收校验。

产物存放在目标项目的 `.codex/codex_native_agents/` 下，记录原生 agent ID、选择的模型档位、降级情况、状态、报告和验证证据。不保存模型原始输出流或供应商会话状态。

## 删除的组件

实现阶段删除以下内容：

- `delegate_to_claude` 入口和 Claude CLI 进程管理；
- Claude session pool、lease、resume 逻辑和 session mode；
- `CODEX_CLAUDE_CHILD_THREAD` 以及 `claude` 的 PATH 探测；
- CC Switch 和 DeepSeek 专用说明；
- thinking-strip proxy 脚本；
- OpenAI 兼容报告 runner；
- 仅用于启动 Claude 的 Windows 和 macOS 包装脚本；
- Claude 专用示例、测试、文档和产物字段；
- 暂时删除 `ccviz`。只有当原生工作流记录证明仪表盘值得长期维护时，再考虑恢复可视化界面。

## 失败处理

- 不合规的 TaskFile 必须在派发前失败。
- 缺少原生代理工具时返回 `BLOCKED`，并清楚说明宿主环境要求。
- 配置模型不可用时退回到继承父线程模型，并明确记录，不得静默忽略。
- 子代理返回 `NEEDS_CONTEXT` 时，通过 `send_input` 补充范围明确的上下文，默认不传入完整父线程对话。
- 可写 Scope 冲突时强制串行执行。
- Reviewer 拒绝后不得进入最终验收，应将任务退回 implementer，或执行一次单档升级。
- 被中断或报错的代理必须先关闭并记录，再创建替代代理。

## 测试

自动化测试覆盖：

- 插件 manifest 和 hook manifest 的 schema；
- 委派触发词匹配及宽泛误触发；
- 任务信封和 TaskFile 校验；
- 角色到模型的路由及模型不可用时的降级；
- 并行 Scope 冲突检测；
- 报告解析以及状态一致性；
- 需求符合性、代码质量和 final-verifier 验收门禁；
- Claude 专用命令和环境依赖是否已彻底移除。

模型路由和生命周期边界通过 mock 测试完成，避免消耗真实代理额度。手工 smoke 验证包括：一个 Luna researcher 任务、一个 Terra implementer 任务、一个 Sol final-verifier 任务，以及一组包含两个代理的并行只读任务。只有所有代理都正确关闭，并且工作流记录通过校验，smoke 才算成功。

## 迁移与兼容性

启用原生插件前，必须禁用旧的 `codex-with-cc` 插件，因为两个插件会声明相同的委派触发词。新插件不提供兼容外壳，也不会自动回退到 Claude。

第一个开发版本采用本地、用户级安装。只有原生 smoke 工作流通过后，才处理 marketplace 打包、仓库重命名和公开发布元数据。

## 验收标准

- 所有运行路径都不调用或依赖 Claude Code、CC Switch、DeepSeek 或外部报告模型。
- 明确的委派任务使用 Codex 原生子代理。
- Luna、Terra 和 Sol 按契约选择，并提供安全的父线程继承降级机制。
- 相互独立的任务可以并行执行，且可写 Scope 不重叠。
- 实现类工作流缺少需求符合性审查、代码质量审查或最终验证证据时不得验收。
- 启用新插件时不存在已启用的旧委派 hook，并且插件通过单元测试、契约测试和真实原生子代理 smoke 验证。
