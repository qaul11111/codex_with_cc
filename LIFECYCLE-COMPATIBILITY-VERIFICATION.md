# 生命周期兼容修复记录

日期：2026-09-04（Asia/Shanghai）

## 已安装的修复

- 插件：`codex-with-cc@personal`，已安装且启用。
- 缓存版本：`1.2.0+codex.20260904122117`。
- 源分支：`codex/cc-hardening-v1.1`；本轮未提交或推送 Git。
- 仍使用 Codex 子线程 -> delegate runner -> Claude Code CLI；未改回 native-only。
- 固定启动器已重新生成并指向上述缓存；不是只修改了源码。

修复包含宿主能力预检、真实 worker 启动前检查、分开的执行结束/线程关闭状态、
原始宿主日志和运行记录的绑定与哈希复核、以及最终核验输入与主线程验收的拆分。
六个 skill、hook、角色模板及安装说明已同步。

没有关闭接口的宿主必须明确使用 `terminal-evidence`，不能将 interrupt 视为 close。
有关闭接口的宿主仍要求真实关闭。旧工作流不会自动切换策略。

## 本地验证

```text
/tmp/codex-native-validation.CE2G4F/bin/python -m pytest -q
214 passed, 2 skipped in 29.14s
```

2 项跳过是缺少 PowerShell 的 Windows wrapper 执行测试。
这些是离线单测/模拟运行，不是新的 Claude Code 实际调用验收。

- 源码与缓存的 skills、hook 内容一致。
- 源码与已安装缓存的插件结构验证通过；六个 skill 的 quick_validate 通过。
- `git diff --check` 通过。
- `codex plugin list --marketplace personal --json` 确认上述版本 installed/enabled。
- 新增生命周期测试覆盖缺少能力、迁移授权、备份保留、伪造关闭拒绝、日志/运行绑定、
  活跃 PID、锁未释放、状态恢复、dry-run、日志修改、旧 BLOCKED 保留和自依赖验收。

## 旧 Android A 工作流迁移

目标：`android-app-a-20260904-160829`，位于 MyKnowledge 的
`.codex/codex_with_cc/claude-delegate/`。

实际核查到 10 次对应的原始 Codex 子线程终止事件、终态运行记录、退出码、
已退出的 runner PID 和已释放的 session lease。经用户批准后，逐条补录执行证据。

结果：`settled: 10`，`pending: 0`，10 条关闭状态均为 `unsupported`，没有伪造 closed。
补录后又使用已安装 runtime 重新核对全部固定证据。30 份原始 config、status、
Claude 报告的 SHA-256 在迁移前后完全一致。未改知识库正文、catalog、draft 状态
或旧验收文档，也未启动 B。

原工作流的精确备份：

`/Users/wxl/Documents/DevProject/GPTProject/MyKnowledge/.codex/codex_with_cc/claude-delegate/workflow_android-app-a-20260904-160829.before-lifecycle-54510c4be7e64b8a9b93a64353ad4705.json`

当前工作流：

`/Users/wxl/Documents/DevProject/GPTProject/MyKnowledge/.codex/codex_with_cc/claude-delegate/workflow_android-app-a-20260904-160829.json`

`verify-final-inputs` 已通过；完整 `verify-workflow` 仍按预期拒绝：最后一份
final-verifier 报告 `20260904_194352_878_a5ca28c5` 是 BLOCKED，
`finalAcceptance` 保持 `needs-review`。迁移不是将旧验收结果升级为通过。

## 尚需重载后的真实验证

当前任务上下文仍包含旧版强制关闭规则，且没有真实 close_agent 接口，
本轮未创建新子代理、未直接运行 Claude CLI，也未执行新的最终验收。

请重启 Codex，并在 MyKnowledge 的新任务中请求：

> 按已安装的新 codex-with-cc 生命周期策略，继续核验工作流
> android-app-a-20260904-160829。保留所有旧报告，只重新做 A 的最终验收，不启动 B。

新任务应读取新版 skill，以新 TaskFile/新子线程生成最终报告。final-verifier
运行 `verify-final-inputs` 和独立内容/测试检查，不要求自己尚未结束时通过完整工作流
验收；主线程收到报告并补齐生命周期证据后，才运行 `verify_delegate_workflow`。
仍需披露线程关闭不受支持，不能声称已经关闭线程。
