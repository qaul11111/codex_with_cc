# GPT-6.1 Sol 路由升级验证

日期：2026-09-30。分支：`codex/gpt61-sol-routing`。

## 行为变化

- 新任务自动档位增加 `balanced61`（6.1 Sol medium）、`balancedHigh61`（high）、`deliberate61`（xhigh）。常规开发/分析使用 medium；深入实现/调查与常规审查使用 high；复杂规划/审查使用 xhigh。
- `--risk normal|high` 与复杂度独立。高风险强制 strict + Astra；旧 `--complexity high-risk` 不能被 `--risk normal` 降级。严格流程最终验证保留 Astra。
- 普通工作仍为 standard：当前源码检查和主程审查，不增加冗余 final-verifier。固定模型、精确能力匹配、原始执行证据和最多两次尝试的要求保持。
- 旧 `balanced` / `balancedHigh` 保持 GPT-6 Sol medium/high 的身份，兼容已有工作流、回执和明确固定选择。新路由不会自动回落到旧 Sol。
- 任意 6.1 Sol 档位发生有依据的能力/质量失败后，最多一次直接升级到 Astra；输入、权限、工具故障不靠升级模型解决。

## 验证记录

- 完整离线测试：333 passed in 14.07s。包括旧待派工任务和完成回执重新加载并验收，高风险/复杂度组合，CLI 风险参数，模型/强度精确匹配，失败升级和已有证据边界。
- 独立 Sol/high 只读复核未发现可操作回归，并在冻结快照上执行 167 项重点测试全部通过；原始子代理日志已登记并确认结束。
- 两个修改技能通过 skill-creator `quick_validate.py`；`git diff --check` 通过。
- CLI 安装版本 `0.1.0+codex.20260930033849`，installed/enabled；31 个技能、运行时、钩子及清单文件与源文件一致。
- 独立启动的 app-server 已读取新版全部 6 个技能和 `gpt-6.1-sol` 模型。有效默认配置为 6.1 Sol/high。
- CC Switch 当前 Codex 提供商配置与 Codex 一致。订阅目录保持 272000 × 95% = 258400 有效上下文，没有套用公开 API 的百万上下文。已有模型、认证及其他提供商设置经备份比对保留。
- 当前中转 `/models` 含新模型；两次真实 Responses 请求完成函数工具往返，响应模型均为 `gpt-6.1-sol`。这是可用性检查，不是质量、速度或费用基准。

## 原生派工边界

本次对话的原生 spawn 工具目录尚未公布 `gpt-6.1-sol`，因此没有把旧 Sol 当成 6.1，也没有伪造 6.1 原生子代理执行。当前目录下新普通任务会按既有规则选取可用的 Astra；模型选择器/远端 API 支持新模型不等于当前 spawn 工具支持。

新会话可加载新配置和插件，但仍须按其实际工具目录预检。完整的 6.1 原生派工还需在明确公布该模型/强度的新上下文验证。此次没有重启客户端或中断正在进行的对话。

本地配置备份在 `~/.codex/backups/gpt61-sol/20260930T032507Z`。含凭据的备份留在用户本机，不纳入仓库。
