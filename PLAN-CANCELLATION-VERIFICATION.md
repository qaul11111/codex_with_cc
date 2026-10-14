# 计划撤销与生命周期提示验证

验证日期：2026-09-06。已安装版本：`1.2.0+codex.20260906051541`。

## 改动

- 宿主不提供关闭接口时，已核验结束的执行显示“执行已结束；宿主不提供线程关闭接口。” 原始 `closeStatus: unsupported` 保留在审计数据中。尚未派发、终态证据未齐的情形分别提示，不宣称执行结束。
- 新增 `runtime.py cancel-prepared-task -PlanFile <plan.json> -Reason <reason>`，用于正式撤销未派发、未执行的计划。核对工作流、启动声明、运行产物和原始宿主派发记录；已经启动的计划拒绝撤销。
- 撤销保留原计划、原工作流备份、原因、时间、主任务身份和文件哈希，不生成成功运行。相同原因重试保持幂等，不能覆盖原撤销原因。
- 已撤销计划在派发、原生结果导入和固定启动器入口被拒绝。后续需要同名工作时可准备新计划。工作流验收重新校验撤销凭据；缺失或改动的审计证据不能放行。

## 回归与安装

- 针对性回归：72 项通过。
- 完整回归：398 项通过、2 项跳过，33.08 秒。
- 插件结构校验、收尾技能校验、`git diff --check` 通过。
- 通过 personal 市场更新安装；插件状态为 installed、enabled。源码与安装缓存的 97 个技能、运行和钩子文件逐一匹配。
- 固定启动器已指向新安装版本，解释器为稳定的 Python 3.13.15。

证据位于 [本轮验证目录](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/plan-cancel-20260906/)：`focused-tests.log`、`full-tests.log`、`install.json`、`cache-verification.json`。

## 真实 Web 工作流

工作流：`web-improve-20260906`，项目：`/Users/wxl/Documents/DevProject/GPTProject/MyKnowledge`。

使用已安装的新命令撤销 `runner` 计划 `90015673a5084b948f723642c0a1e1e0`。原因：runner 计划从未派发；相关验证脚本已由原主任务完成并通过检查，撤销重复的执行计划。

随后执行已安装运行时的 `verify-workflow`，结果通过。整体状态由 `pending-task` 变为 `accepted`；两个实际子任务均已核验终态，`settled: 2`、`pending: 0`。保留 `closeStatus: unsupported`，输出上述明确提示。

对 48 个原工作流产物逐一比对：仅工作流索引发生变化，新增两份撤销审计文件；原计划、报告、运行及检查证据未改变。`runs`、`tasks`、`agentAttempts`、`mainReview`、执行与生命周期策略均保持原值。没有修改 Web 项目源代码。

- [真实撤销输出](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/plan-cancel-20260906/live-cancel.json)
- [真实工作流验收输出](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/plan-cancel-20260906/live-verify.log)
- [产物与字段比对](/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC/.codex/plan-cancel-20260906/live-verification.json)
- 撤销凭据：`/Users/wxl/Documents/DevProject/GPTProject/MyKnowledge/.codex/web-improve-20260906/cancellations/6e2e0f04c9b14976ab12d3911f0cb1ea.json`

## 恢复与使用

修改前备份位于 `/Users/wxl/.codex/backups/codex-with-cc/20260906-130324-plan-cancel`，包含当时源码、已安装插件、启动器及原工作流。

后续新任务加载新版技能说明。已有任务可使用新安装的运行时命令；宿主本身仍未提供线程关闭接口，插件不伪造关闭结果。本轮变更未提交或推送 Git。
