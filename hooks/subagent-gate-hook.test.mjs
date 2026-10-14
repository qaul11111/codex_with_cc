import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const hook = fileURLToPath(new URL("./subagent-gate-hook.mjs", import.meta.url));
const launcher = path.join(process.env.CODEX_HOME || path.join(os.homedir(), ".codex"), "bin", "codex-with-cc-launch");
function check(command, options = {}) {
  const result = spawnSync(process.execPath, [hook], {
    input: JSON.stringify({hook_event_name: "PreToolUse", tool_name: "functions.exec_command",
      tool_input: {cmd: command, ...options}}), encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim() ? JSON.parse(result.stdout).hookSpecificOutput : {};
}

test("quoted Python file-writing and copy heredocs are data", () => {
  for (const command of [
    "python3 - <<'PY'\nfrom pathlib import Path\nimport shutil\nshutil.copy2(Path.home()/'.codex/bin/codex-with-cc-launch', Path('/tmp/backup'))\nPY",
    "python3 - <<'PY'\nfrom pathlib import Path\nPath('/tmp/report.md').write_text('''Example:\nclaude -p \"task\"\n/Users/example/.codex/bin/codex-with-cc-launch\ndelegate_to_claude.sh\n''')\nPY",
    "cat <<'MD' > /tmp/report.md\nclaude -p \"documentation\"\nMD",
    "printf '%s\\n' 'claude -p documentation' > /tmp/report.md",
    `cp '${launcher}' /tmp/launcher.backup`,
    `rg -n 'codex-with-cc-launch' README.md`,
    `cat '${launcher}'; touch /tmp/documentation-marker`,
  ]) assert.deepEqual(check(command), {}, command);
});

test("direct execution, wrappers, substitutions and shell heredocs remain denied", () => {
  for (const command of [
    'claude -p "task"', 'env -u TOKEN claude -p task', 'sudo -u worker claude -p task',
    'command -- claude -p task', 'nohup claude -p task', "sh -c 'claude -p task'",
    'echo "$(claude -p task)"', 'value=`claude -p task`',
    "bash <<'SH'\nclaude -p task\nSH", "cat <<MD\n$(claude -p task)\nMD",
    "env bash <<'SH'\nclaude -p task\nSH", "env -u FOO bash <<'SH'\nclaude -p task\nSH",
    "cat <<MD\n'$(claude -p task)'\nMD",
    "eval 'claude -p task'", 'cat <(claude -p task)',
    "echo '<<EOF'\nclaude -p task\nEOF",
    "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['claude', '-p', 'task'])\nPY",
    "python3 - <<'PY'\nprint('doc')\nPY\nclaude -p task",
  ]) assert.equal(check(command).permissionDecision, "deny", command);
});

test("launcher path arguments and wrappers cannot broaden the fixed shape", () => {
  for (const command of [
    `${launcher} --help`, '/tmp/codex-with-cc-launch', `env ${launcher}`,
    `echo "$(${launcher})"`, `sh -c '${launcher}'`,
    `cat '${launcher}' | bash`, `bash '${launcher}'`,
    `rg --pre='claude -p task' codex-with-cc-launch README.md`,
    `sed -n 'e claude -p task' '${launcher}'`,
    `sed -i '' x '${launcher}'`,
  ]) assert.equal(check(command).permissionDecision, "deny", command);
  assert.deepEqual(check(launcher), {});
});

test("process descriptors require runtime plan and host validation", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "cc-hook-process-"));
  try {
    fs.writeFileSync(path.join(directory, "launch.json"), JSON.stringify({invocation: "codex_with_cc_process"}));
    assert.equal(check(launcher, {workdir: directory}).permissionDecision, "deny");
    fs.writeFileSync(path.join(directory, "launch.json"), "{");
    assert.equal(check(launcher, {workdir: directory}).permissionDecision, "deny");
  } finally { fs.rmSync(directory, {recursive: true, force: true}); }
});
