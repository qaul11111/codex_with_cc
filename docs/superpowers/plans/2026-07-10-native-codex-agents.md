# Native Codex Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `codex_with_cc` 硬 fork 改造成只使用 Codex 原生子代理的 `codex-native-agents` 插件，并用 Luna、Terra、Sol 完成分档路由、并行派发和三阶段验收。

**Architecture:** 插件仍由 skills、hooks 和本地 Python 校验运行时组成。Codex 主线程直接调用 `spawn_agent`、`send_input`、`wait_agent` 和 `close_agent`；Python 运行时只负责 TaskFile、模型路由、Scope 冲突、结构化报告和工作流验收记录，不调用任何模型或代理进程。

**Tech Stack:** Codex plugin manifest、Markdown skills、Node.js hooks、Python 3 标准库、pytest。

## Global Constraints

- 运行时不得调用或依赖 Claude Code、CC Switch、DeepSeek 或外部报告模型。
- 子代理必须使用原生 `spawn_agent`，并显式设置 `fork_context: false`。
- 默认路由为 Luna researcher、Terra implementer/reviewer、Sol final-verifier。
- 模型名不可用时必须回退到继承父线程，并记录 fallback；hook 不得因固定模型名漂移而卡死。
- 并行可写任务必须有互不重叠的 Scope；冲突时强制串行。
- Implementer 必须通过 spec review、quality review 和 final-verifier 后才能验收。
- 子代理不得继续创建嵌套子代理，只有主线程可以派发。
- 新插件启用前必须保持旧 `codex-with-cc` 插件禁用。
- 第一个版本不恢复 `ccviz`，不实现精确金额或额度计费。

---

## Target File Structure

```text
.codex-plugin/plugin.json                         # 新插件身份和展示信息
hooks/hooks.json                                  # Codex hook 声明
hooks/native-agent-gate-hook.mjs                  # 原生 spawn 协议校验
skills/codex-native-agents/
  SKILL.md                                        # 统一入口
  CODEX_NATIVE_AGENTS.md                          # 人类可读完整契约
  contract.json                                   # 机器可读单一事实源
  agents/openai.yaml                              # skill 展示元数据
  scripts/native_agents.py                        # 统一 CLI
  scripts/codex_native_agents_runtime/
    __init__.py
    common.py                                     # 常量和错误类型
    contract.py                                   # contract.json 加载
    task_contract.py                              # TaskFile 校验
    routing.py                                    # 角色/复杂度到模型档位
    reports.py                                    # Worker 报告解析
    scope.py                                      # Scope 规范化和冲突检测
    workflow.py                                   # workflow JSON 和验收门禁
    cli.py                                        # init/register/record/verify 命令
skills/codex-native-agents-{planning,dispatching,worker,reviewing,finishing}/
  SKILL.md
  agents/openai.yaml
tests/
  task_helpers.py
  test_native_plugin_manifest.py
  test_native_contract.py
  test_native_runtime.py
  test_native_hooks.py
  test_no_legacy_claude.py
```

## Task 1: Native Plugin Identity And Contract

**Files:**
- Modify: `.codex-plugin/plugin.json`
- Create: `skills/codex-native-agents/contract.json`
- Create: `skills/codex-native-agents/SKILL.md`
- Create: `skills/codex-native-agents/CODEX_NATIVE_AGENTS.md`
- Create: `skills/codex-native-agents/agents/openai.yaml`
- Create: `tests/test_native_plugin_manifest.py`
- Create: `tests/test_native_contract.py`

**Interfaces:**
- Consumes: approved Native Codex Only design.
- Produces: plugin name `codex-native-agents`, invocation contract `codex_native_agents_workflow`, artifact schema `1`, and the shared contract fields used by every later task.

- [ ] **Step 1: Write failing manifest and contract tests**

```python
def test_native_plugin_manifest(repo):
    manifest = json.loads((repo / ".codex-plugin/plugin.json").read_text())
    assert manifest["name"] == "codex-native-agents"
    assert manifest["version"] == "0.1.0"
    assert "Claude" not in json.dumps(manifest)
    assert "hooks" not in manifest
    assert (repo / "hooks/hooks.json").exists()


def test_model_profiles_are_soft_policy(contract):
    assert contract["spawn"]["forkContext"] is False
    assert contract["spawn"]["fallbackPolicy"] == "inherit_parent"
    assert contract["modelProfiles"]["economy"] == {
        "model": "gpt-5.6-luna", "reasoningEffort": "medium"
    }
    assert contract["modelProfiles"]["balanced"] == {
        "model": "gpt-5.6-terra", "reasoningEffort": "medium"
    }
    assert contract["modelProfiles"]["frontier"] == {
        "model": "gpt-5.6-sol", "reasoningEffort": "high"
    }
```

- [ ] **Step 2: Run tests and confirm the old identity fails**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_plugin_manifest.py tests/test_native_contract.py -q`

Expected: FAIL because the manifest still says `codex-with-cc` and the native contract does not exist.

- [ ] **Step 3: Create the native manifest and contract**

The contract must define these exact stable fields:

```json
{
  "schemaVersion": 1,
  "invocationContract": "codex_native_agents_workflow",
  "artifactSchemaVersion": 1,
  "spawn": {
    "forkContext": false,
    "fallbackPolicy": "inherit_parent",
    "maxEscalations": 1
  },
  "modelProfiles": {
    "economy": {"model": "gpt-5.6-luna", "reasoningEffort": "medium"},
    "balanced": {"model": "gpt-5.6-terra", "reasoningEffort": "medium"},
    "balancedHigh": {"model": "gpt-5.6-terra", "reasoningEffort": "high"},
    "frontier": {"model": "gpt-5.6-sol", "reasoningEffort": "high"}
  },
  "roleProfiles": {
    "planner": "balancedHigh",
    "implementer": "balanced",
    "researcher": "economy",
    "reviewer": "balancedHigh",
    "final-verifier": "frontier"
  }
}
```

Also retain the approved roles, report headings, status values, review kinds, required TaskFile sections, and delegation trigger patterns.

- [ ] **Step 4: Write the core skill and human contract**

The core skill must require this task envelope in every child prompt:

```text
[NATIVE_CODEX_AGENT_TASK]
WorkflowId: native-auth-workflow
TaskId: auth-token-implementation
Role: implementer
TaskFile: .codex/codex_native_agents/tasks/auth-token-implementation.md
Scope: src/auth,tests/auth
ModelProfile: balanced
Writable: true
Parallel: false
DispatcherRole: main
[/NATIVE_CODEX_AGENT_TASK]
```

It must also state that the main thread owns dispatch and that workers cannot call `spawn_agent` recursively.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_plugin_manifest.py tests/test_native_contract.py -q`

Expected: PASS.

```bash
git add .codex-plugin/plugin.json skills/codex-native-agents tests/test_native_plugin_manifest.py tests/test_native_contract.py
git commit -m "feat: define native Codex agent contract"
```

## Task 2: Task Validation, Reports, Scope, And Model Routing

**Files:**
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/__init__.py`
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/common.py`
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/contract.py`
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/task_contract.py`
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/routing.py`
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/reports.py`
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/scope.py`
- Create: `tests/task_helpers.py`
- Create: `tests/test_native_runtime.py`

**Interfaces:**
- Consumes: `contract.json` from Task 1.
- Produces: `validate_task_file()`, `route_for_task()`, `parse_worker_report()`, and `scopes_overlap()` for the workflow and CLI tasks.

- [ ] **Step 1: Write failing runtime tests**

```python
def test_route_for_task_uses_role_and_risk():
    assert route_for_task("researcher", "normal").profile == "economy"
    assert route_for_task("implementer", "normal").profile == "balanced"
    assert route_for_task("implementer", "complex").profile == "balancedHigh"
    assert route_for_task("final-verifier", "high-risk").profile == "frontier"


def test_unavailable_model_falls_back_to_parent():
    route = route_for_task("researcher", "normal", available_models={"gpt-5.6-terra"})
    assert route.model is None
    assert route.fallback == "inherit_parent"


def test_parallel_writable_scopes_must_not_overlap():
    assert scopes_overlap(["src/auth"], ["src/auth/token.py"])
    assert not scopes_overlap(["src/auth"], ["src/billing"])
```

- [ ] **Step 2: Run tests and confirm imports fail**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_runtime.py -q`

Expected: FAIL because the native runtime package does not exist.

- [ ] **Step 3: Implement focused runtime interfaces**

```python
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


@dataclass(frozen=True)
class ModelRoute:
    profile: str
    model: str | None
    reasoning_effort: str | None
    fallback: str | None = None


def route_for_task(
    role: str,
    complexity: str = "normal",
    available_models: set[str] | None = None,
) -> ModelRoute:
    contract = load_contract()
    profile = contract["roleProfiles"][role]
    if role == "implementer" and complexity in {"complex", "high-risk"}:
        profile = "balancedHigh"
    if role in {"planner", "reviewer"} and complexity == "normal":
        profile = "balancedHigh"
    if role == "final-verifier" or complexity == "high-risk":
        profile = "frontier"
    selected = contract["modelProfiles"][profile]
    model = selected["model"]
    if available_models is not None and model not in available_models:
        return ModelRoute(profile, None, None, contract["spawn"]["fallbackPolicy"])
    return ModelRoute(profile, model, selected["reasoningEffort"])


def split_sections(text: str) -> dict[str, str]:
    aliases = load_contract()["taskFile"]["sectionAliases"]
    alias_to_name = {alias.lower(): name for name, values in aliases.items() for alias in values}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = line.strip().lstrip("#").strip().lower()
        if heading in alias_to_name:
            current = alias_to_name[heading]
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def validate_task_file(path: Path, role: str) -> dict[str, str]:
    contract = load_contract()
    if role not in contract["workerRoles"]:
        raise ContractError(f"Unsupported worker role: {role}")
    sections = split_sections(path.read_text(encoding="utf-8"))
    missing = [name for name in contract["taskFile"]["requiredSections"] if not sections.get(name)]
    if missing:
        raise ContractError("Missing or empty task sections: " + ", ".join(missing))
    return sections


@dataclass(frozen=True)
class WorkerReport:
    status: str
    role: str
    final_result: str
    sections: dict[str, str]


def extract_report_sections(text: str) -> dict[str, str]:
    headings = load_contract()["reportHeadings"]
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip().rstrip(":")
        if stripped in headings:
            current = stripped
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def parse_worker_report(text: str) -> WorkerReport:
    contract = load_contract()
    sections = extract_report_sections(text)
    missing = [name for name in contract["reportHeadings"] if not sections.get(name)]
    if missing:
        raise ContractError("Missing or empty report sections: " + ", ".join(missing))
    status = sections["Status"].splitlines()[0].strip()
    role = sections["Role"].splitlines()[0].strip()
    final_result = sections["Final Result"].splitlines()[0].strip()
    if status not in contract["reportStatusValues"] or final_result != status:
        raise ContractError("Status and Final Result must use the same valid token")
    if role not in contract["workerRoles"]:
        raise ContractError(f"Unsupported report role: {role}")
    return WorkerReport(status, role, final_result, sections)


def normalize_scopes(values: Iterable[str]) -> tuple[str, ...]:
    normalized = {PurePosixPath(value.strip()).as_posix().strip("/") for value in values if value.strip()}
    if not normalized or "." in normalized or ".." in normalized:
        raise ContractError("Scopes must be non-empty project-relative paths")
    return tuple(sorted(normalized))


def scopes_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    left_scopes = normalize_scopes(left)
    right_scopes = normalize_scopes(right)
    return any(
        a == b or a.startswith(b + "/") or b.startswith(a + "/")
        for a in left_scopes
        for b in right_scopes
    )
```

`route_for_task()` must never raise solely because a model slug is absent. `parse_worker_report()` must reject missing headings, invalid roles, invalid statuses, and mismatched `Status`/`Final Result`.

- [ ] **Step 4: Run focused tests and commit**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_runtime.py -q`

Expected: PASS.

```bash
git add skills/codex-native-agents/scripts/codex_native_agents_runtime tests/task_helpers.py tests/test_native_runtime.py
git commit -m "feat: add native task validation and model routing"
```

## Task 3: Workflow Recorder And Acceptance Gates

**Files:**
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/workflow.py`
- Create: `skills/codex-native-agents/scripts/codex_native_agents_runtime/cli.py`
- Create: `skills/codex-native-agents/scripts/native_agents.py`
- Create: `tests/test_native_workflow.py`

**Interfaces:**
- Consumes: Task 2 validators and routes.
- Produces: one CLI with `init`, `register-task`, `record-run`, and `verify` subcommands and one `workflow_wf-example.json` record for the example workflow.

- [ ] **Step 1: Write failing workflow-gate tests**

```python
def test_implementer_requires_two_reviews_and_final_verifier(tmp_path):
    workflow = new_workflow("wf-test")
    register_task(workflow, task_id="impl", role="implementer", scopes=("src",), writable=True)
    record_run(workflow, task_id="impl", agent_id="agent-1", report=done_report("implementer"))
    with pytest.raises(WorkflowError, match="spec review"):
        verify_workflow(workflow)


def test_parallel_writable_overlap_is_rejected():
    workflow = new_workflow("wf-parallel")
    register_task(workflow, task_id="a", role="implementer", scopes=("src/auth",), writable=True, parallel=True)
    with pytest.raises(WorkflowError, match="overlap"):
        register_task(workflow, task_id="b", role="implementer", scopes=("src/auth/token.py",), writable=True, parallel=True)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_workflow.py -q`

Expected: FAIL because the workflow module and CLI do not exist.

- [ ] **Step 3: Implement workflow records**

Every workflow JSON must use this top-level shape:

```json
{
  "artifactSchema": 1,
  "invocationContract": "codex_native_agents_workflow",
  "workflowId": "wf-example",
  "status": "running",
  "tasks": {},
  "runs": {},
  "finalAcceptance": null
}
```

Each run records `agentId`, `taskId`, `modelProfile`, `requestedModel`, `reasoningEffort`, `fallback`, `reportStatus`, `reportFinalResult`, `reportPath`, and timestamps. The CLI writes under `.codex/codex_native_agents/workflows` unless `--artifact-root` is passed.

- [ ] **Step 4: Implement the CLI contract**

```bash
python3 skills/codex-native-agents/scripts/native_agents.py init --workflow-id wf-example
python3 skills/codex-native-agents/scripts/native_agents.py register-task --workflow-id wf-example --task-id research --role researcher --task-file .codex/codex_native_agents/tasks/research.md --scope src --model-profile economy
python3 skills/codex-native-agents/scripts/native_agents.py record-run --workflow-id wf-example --task-id research --agent-id agent-123 --report-file .codex/codex_native_agents/reports/research.md
python3 skills/codex-native-agents/scripts/native_agents.py verify --workflow-id wf-example
```

Reviewer registration additionally requires `--review-for-task-id` and `--review-kind spec|quality`.

- [ ] **Step 5: Run focused tests and commit**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_workflow.py -q`

Expected: PASS.

```bash
git add skills/codex-native-agents/scripts tests/test_native_workflow.py
git commit -m "feat: record and verify native agent workflows"
```

## Task 4: Native Spawn Hook Gate

**Files:**
- Modify: `hooks/hooks.json`
- Create: `hooks/native-agent-gate-hook.mjs`
- Create: `tests/test_native_hooks.py`

**Interfaces:**
- Consumes: Task 1 contract and task-envelope format.
- Produces: compact SessionStart/UserPromptSubmit context injection and stable PreToolUse validation for native `spawn_agent` calls.

- [ ] **Step 1: Write failing hook tests**

```python
def test_spawn_requires_native_task_envelope(run_hook):
    result = run_hook({
        "hook_event_name": "PreToolUse",
        "tool_name": "multi_agent_v1__spawn_agent",
        "tool_input": {"message": "implement auth", "fork_context": False},
    })
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_model_override_is_not_hard_required(run_hook, compliant_spawn):
    compliant_spawn["tool_input"].pop("model", None)
    assert run_hook(compliant_spawn) == {}


def test_fork_context_true_is_denied(run_hook, compliant_spawn):
    compliant_spawn["tool_input"]["fork_context"] = True
    result = run_hook(compliant_spawn)
    assert "fork_context: false" in result["hookSpecificOutput"]["permissionDecisionReason"]
```

- [ ] **Step 2: Run tests and confirm the Claude gate fails them**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_hooks.py -q`

Expected: FAIL because `subagent-gate-hook.mjs` enforces Claude-specific metadata.

- [ ] **Step 3: Implement the native hook**

The hook must:

- load `skills/codex-native-agents/contract.json`;
- recognize namespaced `spawn_agent` tool names by tail component;
- combine plain `message` and text `items` before envelope validation;
- require all task-envelope fields and `DispatcherRole: main`;
- require `fork_context` to be explicitly false;
- permit explicit model overrides and parent inheritance;
- reject direct `claude` and `delegate_to_claude` shell execution as legacy paths;
- avoid blocking read-only inspection of legacy text during development;
- inject worker guidance that forbids nested `spawn_agent` calls.

- [ ] **Step 4: Run hook tests and commit**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_hooks.py -q`

Expected: PASS.

```bash
git add hooks tests/test_native_hooks.py
git commit -m "feat: gate native Codex agent dispatch"
```

## Task 5: Workflow Skills, Documentation, And Claude Removal

**Files:**
- Create: `skills/codex-native-agents-planning/SKILL.md`
- Create: `skills/codex-native-agents-planning/agents/openai.yaml`
- Create: `skills/codex-native-agents-dispatching/SKILL.md`
- Create: `skills/codex-native-agents-dispatching/agents/openai.yaml`
- Create: `skills/codex-native-agents-worker/SKILL.md`
- Create: `skills/codex-native-agents-worker/agents/openai.yaml`
- Create: `skills/codex-native-agents-reviewing/SKILL.md`
- Create: `skills/codex-native-agents-reviewing/agents/openai.yaml`
- Create: `skills/codex-native-agents-finishing/SKILL.md`
- Create: `skills/codex-native-agents-finishing/agents/openai.yaml`
- Modify: `AI_INSTALL.md`
- Modify: `README.md`
- Modify: `docs/README.zh-CN.md`
- Modify: `docs/VERIFICATION.md`
- Modify: `docs/plugin-layout.md`
- Delete: `blog/`
- Delete: `examples/`
- Delete: `scripts/`
- Delete: `skills/codex-with-cc/`
- Delete: `skills/codex-with-cc-planning/`
- Delete: `skills/codex-with-cc-dispatching/`
- Delete: `skills/codex-with-cc-worker/`
- Delete: `skills/codex-with-cc-reviewing/`
- Delete: `skills/codex-with-cc-finishing/`
- Replace: legacy `tests/test_*.py` files with `tests/test_no_legacy_claude.py`

**Interfaces:**
- Consumes: native contract, CLI, and hook behavior from Tasks 1-4.
- Produces: a self-consistent distributable plugin with no runnable Claude path.

- [ ] **Step 1: Write the failing legacy-removal test**

```python
FORBIDDEN_RUNTIME_TOKENS = (
    "delegate_to_claude",
    "CODEX_CLAUDE_CHILD_THREAD",
    "claude_cli.py",
    "thinking_strip_proxy",
    "openai_compatible_report",
    "PrimaryReuse",
    "PrimaryAnchor",
    "ParallelPool",
)


def test_no_legacy_runtime_paths_remain(repo):
    scanned = scan_runtime_and_docs(repo)
    for token in FORBIDDEN_RUNTIME_TOKENS:
        assert token not in scanned
```

The license, Git history, design documents, and an explicit migration note may mention Claude historically; the executable plugin surface, active docs, tests, and manifests may not.

- [ ] **Step 2: Run the test and confirm it finds legacy paths**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest tests/test_no_legacy_claude.py -q`

Expected: FAIL and list the old delegate/session/proxy paths.

- [ ] **Step 3: Rewrite staged skills around native tools**

The dispatching skill must use this sequence:

```text
validate TaskFile
init/register workflow task
spawn all independent tasks before waiting
record agent id and requested model profile
continue non-overlapping main-thread work
wait only when the critical path needs the result
record the structured report
run spec review, quality review, and final verification
close every completed or failed agent
verify workflow
```

- [ ] **Step 4: Remove Claude-only code and rewrite active docs**

Use Git-aware deletion for the exact directories listed above. Preserve `LICENSE` and the two approved design documents. README and install docs must identify the fork repository and describe local user-scope development installation without claiming marketplace publication.

- [ ] **Step 5: Run the full unit suite and commit**

Run: `PYTHONNOUSERSITE=1 python3 -m pytest -q`

Expected: all native tests PASS with no legacy test collection errors.

```bash
git add -A
git commit -m "refactor: remove Claude delegation runtime"
```

## Task 6: Local Installation And Real Native-Agent Smoke

**Files:**
- Modify only if verification finds a defect: native plugin files created in Tasks 1-5.
- Create in smoke target, not committed: `.codex/codex_native_agents/tasks/smoke-*.md`
- Create in smoke target, not committed: `.codex/codex_native_agents/workflows/workflow_native-smoke.json`

**Interfaces:**
- Consumes: complete plugin package.
- Produces: evidence that the installed plugin routes native child agents, runs independent tasks concurrently, records reports, closes agents, and passes final acceptance.

- [ ] **Step 1: Run static and unit verification**

```bash
jq empty .codex-plugin/plugin.json hooks/hooks.json skills/codex-native-agents/contract.json
node --check hooks/native-agent-gate-hook.mjs
PYTHONNOUSERSITE=1 python3 -m pytest -q
```

Expected: JSON parsing succeeds, Node syntax check succeeds, and all tests PASS.

- [ ] **Step 2: Install as a local user-scoped development plugin**

Use `plugin-creator` to create the personal marketplace entry and the canonical `~/plugins/codex-native-agents` source path. Replace only the newly generated scaffold directory with a symlink to this repository, then use the cachebuster helper and CLI reinstall flow. Do not hand-edit `marketplace.json` or `~/.codex/config.toml`.

```bash
python3 /Users/wxl/.codex/skills/.system/plugin-creator/scripts/create_basic_plugin.py codex-native-agents --with-marketplace
python3 /Users/wxl/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py ~/plugins/codex-native-agents
python3 /Users/wxl/.codex/skills/.system/plugin-creator/scripts/read_marketplace_name.py
codex plugin add codex-native-agents@personal
```

Before reinstalling, confirm `codex-with-cc@aiskyhub` remains disabled. The generated source-path replacement is allowed only when `~/plugins/codex-native-agents` is the scaffold created by this task and contains no user work.

Expected: plugin list reports `codex-native-agents` installed and enabled, with hooks parsed without warnings.

- [ ] **Step 3: Run one two-agent parallel read-only smoke batch**

Create two disjoint researcher TaskFiles, initialize one workflow, register both as `parallel=true`, and spawn both before any wait:

```text
research-a -> gpt-5.6-luna / medium / Scope README.md
research-b -> gpt-5.6-luna / medium / Scope skills/codex-native-agents/contract.json
```

Expected: both return structured `DONE` reports, have different agent IDs, and close cleanly.

- [ ] **Step 4: Run Terra implementer reviews and Sol final verification**

Use a documentation-only smoke change with disjoint scope. Route implementer to Terra, spec/quality reviewers to Terra, and final-verifier to Sol. Record all reports through the CLI.

Expected: workflow verification rejects the implementer before reviews, rejects it before final-verifier, then passes after all three gates are accepted.

- [ ] **Step 5: Verify artifacts and repository state**

```bash
python3 skills/codex-native-agents/scripts/native_agents.py verify --workflow-id native-smoke
git status --short
git diff --check
```

Expected: workflow verification passes; only intentional source changes are present; smoke artifacts remain untracked or ignored.

- [ ] **Step 6: Commit any smoke-derived fixes**

If smoke exposed a defect, add a failing regression test, apply the minimal fix, rerun the full suite and smoke, then commit:

```bash
git add -A
git commit -m "fix: harden native agent smoke workflow"
```

If no defect is found, do not create an empty commit.

## Final Verification

- [ ] `PYTHONNOUSERSITE=1 python3 -m pytest -q` passes.
- [ ] `jq empty` passes for all plugin JSON files.
- [ ] `node --check hooks/native-agent-gate-hook.mjs` passes.
- [ ] `rg` finds no active Claude delegate, session-pool, proxy, or external report runtime.
- [ ] Plugin installs and hooks parse in the current Codex environment.
- [ ] Luna parallel research smoke passes and both agents close.
- [ ] Terra implementation/review and Sol final-verifier smoke passes.
- [ ] Workflow verification proves spec, quality, and final-verifier gates.
- [ ] Old `codex-with-cc@aiskyhub` remains disabled.
- [ ] Final `git status` and diff contain no unrelated changes.
