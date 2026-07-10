# Codex Native Agents

本仓库将原有工作流重构为仅使用 Codex 原生子代理的本地开发插件。主线程负责拆解、派发、审查、验收和对用户交付；子代理只执行边界明确的 TaskFile，并返回结构化报告。

开发源为 [qaul11111/codex_with_cc](https://github.com/qaul11111/codex_with_cc)。当前仅支持本地、用户级开发安装，不宣称已发布到 marketplace。安装步骤见 [AI_INSTALL.md](../AI_INSTALL.md)，验证步骤见 [VERIFICATION.md](VERIFICATION.md)。

五个工作流技能分别覆盖规划、派发、执行、审查和收尾。实现类任务必须经过需求符合性审查、质量审查和最终验证，所有子代理都必须关闭并通过工作流验证后才能完成交付。
