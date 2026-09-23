# GPT-6 插件安装与真实测试

日期：2026-09-23。分支：`codex/gpt6-adaptive-routing`。

## 安装结果

- 插件：`codex-native-agents@personal`，版本 `0.1.0+codex.20260923044134`。
- 本地入口 `~/plugins/codex-native-agents` 指向本分支的独立 worktree。
- 新插件 installed/enabled；旧 `codex-with-cc@personal` 仍保持禁用。
- 新 app-server 扫描到六个已启用技能和三个 Hook；只为这三个已审查 Hook 的精确哈希写入信任。
- 独立临时 app-server 会话实测 SessionStart、UserPromptSubmit 均 completed；Sol 确认技能和启动调度上下文均已加载。临时会话没有写入持久任务历史。
- 三模型目录和约 258K 的普通可用上下文保持原配置。
- 本次真实派工由主控读取已安装运行时后执行；原任务上下文不会因安装而热加载新技能。

## 真实执行

使用独立合成测试数据，没有请求业务服务或修改业务代码。子代理均通过
`prepare-spawn` 生成的原生工具参数启动；原始宿主日志核对了模型、思考强度、
最终报告和终态。这里的模型身份是宿主记录，不能证明中转服务内部实现或账单。

| 任务 | 实际宿主模型 / 强度 | 结果 |
| --- | --- | --- |
| 12 条事件日志筛查 | GPT-6 Luna / low | 分类计数正确，但最终失败列表漏掉未重试的 401 请求 r4 |
| Python 事件统计函数实现 | GPT-6 Sol / medium | 通过 9 组主控验收用例，含 701 个状态值、无效类型和单次迭代输入 |
| 独立验收用例设计 | GPT-6 Astra / xhigh | 提出边界、布尔值、浮点数、Unicode 空白和混合输入等用例；混合输入通过实现验证 |
| 被拒收结果的独立复核 | GPT-6 Sol / medium | 正确识别 r3=503、r4=401，结构化结果通过检查，复核工作流 accepted |

首轮原始报告和失败检查均保留，首轮工作流未被改成 accepted。纠正是主控识别
错误后明确重新规划的任务，不是把自报 DONE 的旧任务自动升级，也没有重写旧报告。
这证明了验收的必要性，不能以一次样例推断 Luna 的总体准确率。

## 实测发现并修复的问题

当前中转会保留响应消息的上游 turn ID，它不同于宿主 task_started/task_complete
使用的 turn ID。旧读取器因此无法提取已经完成的真实最终报告。

现在只在当前宿主 turn 内的最后一个合格 assistant final 与该 turn 首个
task_complete.last_agent_message 逐字相等时兼容此差异。保留身份、模型、强度、
终态及原日志哈希校验。旧 turn、commentary、缺失/不匹配回执、后续冒充终态和
被更新的旧 final 都不能通过。新增 9 个回归用例。
独立只读审查另检查了 12 个边界情况，无阻断问题。

真实启动还发现宿主注入的是 `PLUGIN_ROOT`，而旧启动命令只读取
`CODEX_PLUGIN_ROOT`。现统一优先读取当前变量，并兼容旧变量。增加 4 项执行
完整 manifest 启动命令的测试，覆盖当前变量、旧变量、当前变量优先和缺失变量；
之前仅直接执行模块的测试没有覆盖外层启动命令。最终全套 **239 passed**，
新进程也证实原先失败的启动 Hook 已能成功运行。

## 验收边界与证据

- 主控实测了 standard 验收和拒收；strict 的独立审查链及失败自动升级仍以离线回归为证据，本次未做新的真实运行。
- 当前宿主没有 close_agent；子任务有原始终态证据，关闭状态记录为 unsupported。
- 合成夹具位于 Git 忽略的 `.codex` 目录，实际内容由显式执行的验收命令检查；不能依赖仓库快照覆盖这些文件。
- 未测量可比较的速度提升、总 token 成本或订阅额度消耗。

本机完整证据：
`/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/gpt6-install-smoke-20260923/`

安装前备份：
`/Users/wxl/.codex/backups/codex-native-agents/gpt6-install-20260923/`

新建 Codex 任务时会读取新技能和 Hook；继续使用 Astra 作主控即可。
