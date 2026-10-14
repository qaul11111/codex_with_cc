#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";

const FALLBACK_CONTRACT = {
  childThread: { markerName: "CODEX_CLAUDE_CHILD_THREAD", markerValue: "1" },
  spawn: {
    model: "",
    modelPolicy: "inherit_parent",
    reasoningEffort: "",
    reasoningEffortPolicy: "inherit_parent",
    forkContext: false,
    forkTurns: "none",
  },
  provenance: {
    hostTranscriptFields: ["transcript_path", "transcriptPath"],
    subagentSessionMetaSignals: ["source.subagent", "thread_source=subagent", "parent_thread_id"],
    fallbackPolicy: "child_marker",
  },
  workerRoles: ["planner", "implementer", "researcher", "reviewer", "final-verifier"],
  triggerPatterns: [
    "child[- ]?agent",
    "sub[- ]?agent",
    "child[- ]?thread",
    "sub[- ]?thread",
    "delegat(?:e|ion|ing)",
    "worker[- ]?execution",
    "子代理|子线程|多代理|委派|派工|执行层",
  ],
  spawnToolNames: ["spawn_agent", "task", "subagent", "agent", "worker"],
  delegateEntrypointPattern: "delegate_to_claude(?:\\.(?:ps1|sh|cmd|bat))?",
  delegateEntrypointPatterns: [
    "delegate_to_claude(?:\\.(?:ps1|sh|cmd|bat))?",
    "delegate_to_(?:openai(?:_compatible)?(?:_report(?:_only)?)?)(?:\\.(?:ps1|sh|cmd|bat))?",
  ],
};

const ROUTING_CONTEXT = [
  "codex-with-cc platform subagent gate:",
  "- Main may directly finish simple known-location low-risk tasks. Delegate substantial exploration, implementation, tests and repair as coherent codex-with-cc worker tasks; parallelize independent scopes. Main owns decisions and focused acceptance. Discussion alone never starts workers.",
  "- Legacy Claude chain: Codex main thread -> Codex spawn_agent child thread -> delegate_to_claude.* -> Claude Code CLI.",
  "- Read references/astra-workflows.md for prepared routes. Claude requests prefer supported claude-process: main invokes the literal fixed launcher under CODEX_HOME/bin with no arguments and the prepared launch.json directory as cwd. It runs Claude Code CLI without a Codex model carrier; immutable plan, main-host identity and task-specific commands are validated before launch.",
  "- Read the codex-with-cc skill when choosing or executing useful delegation; preserve explicit user routing choices.",
  "- For adaptive workflows use ready-tasks then admit-task; only dispatch admitted plans within capacity and scope boundaries. Process each completion and recompute readiness.",
  "- Configure standard or strict acceptance and configure-lifecycle from actual host tools. claude-process uses process-exit evidence and bounded timeout; it is not a child thread. Native/legacy children need strict-close or terminal-evidence; see references/lifecycle.md.",
  "- record every spawned agent id and bind reviews to the exact implementer run. Close every attempt when supported; otherwise record verified host/runner terminal evidence with closeStatus=unsupported. Never treat interrupt_agent as closure.",
  "- Final-verifier workers run verify-final-inputs, not their own whole-workflow acceptance. The main thread verifies the full workflow after the final report and lifecycle settlement.",
  "- Legacy child spawn metadata inherits the main-thread model/effort; prepared routes use the pinned carrier or native model/effort. Use fork_context=false or fork_turns=none.",
  "- Legacy child launch alone uses CODEX_CLAUDE_CHILD_THREAD=1 and delegate_to_claude.* metadata. Native plans execute directly and use record-native-run. Preserve explicit provider/model routing; missing usage is unknown and speed/cost savings require measurement.",
  "- Strict implementer workflows require current spec review, quality review, and final-verifier acceptance. Standard uses run-checks and record-main-review before main-thread verify-workflow. Dry runs and empty workflows never count as acceptance.",
].join("\n");

function pluginRoot() {
  if (process.env.CLAUDE_PLUGIN_ROOT) {
    return process.env.CLAUDE_PLUGIN_ROOT;
  }
  if (process.env.CODEX_PLUGIN_ROOT) {
    return process.env.CODEX_PLUGIN_ROOT;
  }

  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

function readOptionalText(filePath) {
  try {
    return fs.readFileSync(filePath, "utf8");
  } catch {
    return "";
  }
}

function mergeContract(contract) {
  const delegateEntrypointPatterns = Array.isArray(contract.delegateEntrypointPatterns) && contract.delegateEntrypointPatterns.length > 0
    ? contract.delegateEntrypointPatterns
    : [contract.delegateEntrypointPattern || FALLBACK_CONTRACT.delegateEntrypointPattern];
  return {
    ...FALLBACK_CONTRACT,
    ...contract,
    childThread: { ...FALLBACK_CONTRACT.childThread, ...(contract.childThread || {}) },
    spawn: { ...FALLBACK_CONTRACT.spawn, ...(contract.spawn || {}) },
    provenance: { ...FALLBACK_CONTRACT.provenance, ...(contract.provenance || {}) },
    workerRoles: Array.isArray(contract.workerRoles) ? contract.workerRoles : FALLBACK_CONTRACT.workerRoles,
    triggerPatterns: Array.isArray(contract.triggerPatterns) ? contract.triggerPatterns : FALLBACK_CONTRACT.triggerPatterns,
    spawnToolNames: Array.isArray(contract.spawnToolNames) ? contract.spawnToolNames : FALLBACK_CONTRACT.spawnToolNames,
    delegateEntrypointPatterns,
  };
}

function readContract() {
  const raw = readOptionalText(path.join(pluginRoot(), "skills", "codex-with-cc", "contract.json"));
  if (!raw.trim()) {
    return FALLBACK_CONTRACT;
  }
  try {
    return mergeContract(JSON.parse(raw));
  } catch {
    return FALLBACK_CONTRACT;
  }
}

const CONTRACT = readContract();
const REQUIRED_MODEL = CONTRACT.spawn.model;
const REQUIRED_MODEL_POLICY = CONTRACT.spawn.modelPolicy || (REQUIRED_MODEL ? "fixed" : "inherit_parent");
const REQUIRED_EFFORT = CONTRACT.spawn.reasoningEffort;
const REQUIRED_EFFORT_POLICY = CONTRACT.spawn.reasoningEffortPolicy || (REQUIRED_EFFORT ? "fixed" : "inherit_parent");
const REQUIRED_FORK_CONTEXT = CONTRACT.spawn.forkContext;
const REQUIRED_FORK_TURNS = CONTRACT.spawn.forkTurns || "none";
const CHILD_MARKER_NAME = CONTRACT.childThread.markerName;
const CHILD_MARKER_VALUE = CONTRACT.childThread.markerValue;
const ALLOWED_ROLES = new Set(CONTRACT.workerRoles.map((role) => String(role).toLowerCase()));
const TRIGGER_PATTERNS = CONTRACT.triggerPatterns.map((pattern) => new RegExp(pattern, "i"));
const SPAWN_TOOL_NAMES = new Set(CONTRACT.spawnToolNames.map((name) => String(name).toLowerCase()));
const DELEGATE_ENTRYPOINT_PATTERNS = CONTRACT.delegateEntrypointPatterns.map((pattern) => new RegExp(pattern, "i"));

function bootstrapContext() {
  return ROUTING_CONTEXT;
}

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
  });
}

function parseInput(text) {
  if (!text.trim()) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function writeJson(value) {
  process.stdout.write(JSON.stringify(value));
}

function getEventName(input) {
  return input.hook_event_name || input.hookEventName || input.eventName || "";
}

function getToolName(input) {
  return input.tool_name || input.toolName || "";
}

function getToolInput(input) {
  return input.tool_input || input.toolInput || {};
}

function getShellCommand(toolInput) {
  return prop(toolInput, "command", "cmd") || "";
}

function getPrompt(input) {
  return input.prompt || input.user_prompt || input.userPrompt || "";
}

function stringify(value) {
  if (typeof value === "string") {
    return value;
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function containsSubagentTrigger(text) {
  return TRIGGER_PATTERNS.some((pattern) => pattern.test(text));
}

function additionalContext(eventName) {
  return {
    hookSpecificOutput: {
      hookEventName: eventName,
      additionalContext: bootstrapContext(),
    },
  };
}

function deny(reason) {
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  };
}

function prop(input, snakeName, camelName) {
  if (input && Object.prototype.hasOwnProperty.call(input, snakeName)) {
    return input[snakeName];
  }
  if (input && Object.prototype.hasOwnProperty.call(input, camelName)) {
    return input[camelName];
  }
  return undefined;
}

function isFalse(value) {
  return value === false || value === "false";
}

function toolNameTail(toolName) {
  const parts = String(toolName || "").toLowerCase().split(/(?:__|[.:/\\])+/).filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : "";
}

function isShellToolName(toolName) {
  const normalized = String(toolName || "").toLowerCase();
  const tail = toolNameTail(normalized);
  return normalized === "bash" || tail === "shell_command" || tail === "exec_command";
}

function isWorkflowSpawnToolName(toolName) {
  const normalized = String(toolName || "").toLowerCase();
  const tail = toolNameTail(normalized);
  return SPAWN_TOOL_NAMES.has(normalized) || SPAWN_TOOL_NAMES.has(tail) || normalized.includes("spawn_agent") || normalized.includes("subagent");
}

function isOpaqueCollaborationSpawn(toolName, payload) {
  const normalized = String(toolName || "").toLowerCase();
  const message = prop(payload, "message", "message");
  return normalized.includes("collaborationspawn_agent")
    && typeof message === "string"
    && /^gAAAAA[A-Za-z0-9_-]{80,}={0,2}$/.test(message);
}

function nestedToolUses(toolInput) {
  if (Array.isArray(toolInput?.tool_uses)) {
    return toolInput.tool_uses;
  }
  if (Array.isArray(toolInput?.toolUses)) {
    return toolInput.toolUses;
  }
  return [];
}

function nestedToolName(item) {
  return item?.recipient_name || item?.recipientName || item?.tool_name || item?.toolName || "";
}

function nestedToolInput(item) {
  return item?.parameters || item?.tool_input || item?.toolInput || {};
}

function hasChildMarker(serialized) {
  const pattern = new RegExp(`${CHILD_MARKER_NAME}\\s*(?:=|:)\\s*["']?${CHILD_MARKER_VALUE}["']?`, "i");
  return pattern.test(serialized);
}

function hasDelegateEntrypoint(serialized) {
  return DELEGATE_ENTRYPOINT_PATTERNS.some((pattern) => pattern.test(serialized));
}

function canonicalLauncherPath() {
  const configured = String(process.env.CODEX_HOME || "").trim();
  const codexHome = configured
    ? path.resolve(configured)
    : path.join(os.homedir(), ".codex");
  return path.join(codexHome, "bin", "codex-with-cc-launch");
}

const CANONICAL_LAUNCHER = canonicalLauncherPath();

function isFixedLauncherShellCommand(command) {
  const cmd = String(command || "");
  return cmd === CANONICAL_LAUNCHER
    || cmd === `/bin/zsh -c "${CANONICAL_LAUNCHER}"`;
}

function hasAppRecordedLauncher(command) {
  return /\bcodex-with-cc-launch\b/.test(String(command || ""));
}

function isReadOnlyInspectionCommand(command) {
  // Inspect every segment, including pipelines. A quoted filename mentioning a
  // runner is data, not an invocation. Reject substitutions and redirections.
  if (/\$\(|`|[<>]/.test(command)) return false;
  const segments = shellCommandSegments(command);
  return segments.length > 0 && segments.every(isReadOnlyInspectionSegment);
}

function isReadOnlyInspectionSegment(segment) {
  const tokens = segment.map(unquoteShellToken);
  const executable = shellBasename(tokens[0]);
  if (["pwd", "true"].includes(executable)) return tokens.length === 1;
  if (executable === "rg") {
    return !tokens.some((token) => token === "--pre" || token.startsWith("--pre="));
  }
  if (["grep", "findstr", "select-string", "get-content", "cat", "type", "head", "tail", "nl", "wc"].includes(executable)) {
    return true;
  }
  if (executable === "sed") {
    // Only print-range inspection; sed also has file-write and execution commands.
    let index = 1;
    while (["-n", "-e"].includes(tokens[index])) index += 1;
    return /^(?:\d+|\$)?(?:,(?:\d+|\$))?p$/.test(tokens[index] || "")
      && !tokens.slice(index + 1).some((token) => token.startsWith("-"));
  }
  if (executable === "git") {
    const subcommand = tokens.find((token, index) => index > 0 && !token.startsWith("-")) || "";
    return ["show", "grep", "diff", "status", "log"].includes(subcommand);
  }
  return false;
}

function hasFixedLauncherSpawnReference(serialized) {
  const text = String(serialized || "");
  return text.includes(CANONICAL_LAUNCHER) && /\blaunch\.json\b/i.test(text);
}

function hasTaskFile(serialized) {
  return /(?:^|[\s"'])(?:-TaskFile|--task-file)\b/i.test(serialized);
}

function hasLegacyInlineTask(serialized) {
  return /(?:^|[\s"'])-(?:Task)\b/i.test(serialized);
}

function hasWorkflowId(serialized) {
  return /(?:^|[\s"'])(?:-WorkflowId|--workflow-id)\b/i.test(serialized);
}

function hasTaskId(serialized) {
  return /(?:^|[\s"'])(?:-TaskId|--task-id)\b/i.test(serialized);
}

function roleValue(serialized) {
  const match = serialized.match(/(?:^|[\s"'])(?:-Role|--role)\s+["']?([A-Za-z-]+)/i);
  return match ? match[1].toLowerCase() : "";
}

function hasRole(serialized) {
  return /(?:^|[\s"'])(?:-Role|--role)\b/i.test(serialized);
}

function hasSessionKey(serialized) {
  return /(?:^|[\s"'])(?:-SessionKey|--session-key)\b/i.test(serialized);
}

function hasReviewForTaskId(serialized) {
  return /(?:^|[\s"'])(?:-ReviewForTaskId|--review-for-task-id)\b/i.test(serialized);
}

function hasReviewForRunId(serialized) {
  return /(?:^|[\s"'])(?:-ReviewForRunId|--review-for-run-id)\b/i.test(serialized);
}

function hasReviewKind(serialized) {
  return /(?:^|[\s"'])(?:-ReviewKind|--review-kind)\b/i.test(serialized);
}

function hasLegacyMode(serialized) {
  return /(?:^|[\s"'])(?:-Mode|--mode)\b/i.test(serialized);
}

function hasScope(serialized) {
  return /(?:^|[\s"'])(?:-Scope|--scope)\b/i.test(serialized);
}

function hasAllowParallel(serialized) {
  return /(?:^|[\s"'])-(?:AllowParallel)\b|(?:^|[\s"'])--allow-parallel\b/i.test(serialized);
}

function hasForbiddenEffort(serialized) {
  return false;
}

function unquoteShellToken(token) {
  const value = String(token || "");
  if (value.length >= 2 && ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'")))) {
    return value.slice(1, -1);
  }
  return value;
}

function shellBasename(token) {
  const normalized = unquoteShellToken(token).replaceAll("\\", "/").toLowerCase();
  const parts = normalized.split("/").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : normalized;
}

function tokenizeShell(command) {
  return String(command || "").match(/&&|\|\||[;&|\n\r]|(?:[^\s;&|"'\\]+|\\.|"(?:\\.|[^"\\])*"|'[^']*')+/g) || [];
}

function shellCommandSegments(command) {
  const segments = [];
  let current = [];
  for (const token of tokenizeShell(command)) {
    if (/^(?:&&|\|\||[;&|]|\n|\r)$/.test(token)) {
      if (current.length > 0) {
        segments.push(current);
        current = [];
      }
    } else {
      current.push(token);
    }
  }
  if (current.length > 0) {
    segments.push(current);
  }
  return segments;
}

function isShellAssignment(token) {
  return /^[A-Za-z_][A-Za-z0-9_]*=/.test(unquoteShellToken(token));
}

function optionNeedsValue(token, shortNames, longNames) {
  const value = unquoteShellToken(token);
  if (longNames.some((name) => value === name)) {
    return true;
  }
  return shortNames.some((name) => value === name);
}

function shellSegmentRunsTarget(tokens, target = "claude") {
  let index = 0;
  let wrapperCount = 0;

  while (index < tokens.length && wrapperCount < 16) {
    while (index < tokens.length && isShellAssignment(tokens[index])) {
      index += 1;
    }
    if (index >= tokens.length) {
      return false;
    }

    const executable = shellBasename(tokens[index]);
    const matches = target === "claude"
      ? ["claude", "claude.cmd", "claude.exe"].includes(executable)
      : target === "launcher" ? executable === "codex-with-cc-launch"
        : target === "shell" ? ["sh", "bash", "zsh"].includes(executable)
          : target === "interpreter" ? /^(?:python[\d.]*|node|ruby|perl)$/.test(executable)
        : DELEGATE_ENTRYPOINT_PATTERNS.some((pattern) => pattern.test(executable));
    if (matches) {
      if (target !== "claude") return true;
      const args = tokens.slice(index + 1).map(unquoteShellToken);
      const diagnostic = (args.length === 1 && ["--version", "-v", "--help", "-h"].includes(args[0]))
        || (args.length === 2 && args[0] === "auth" && args[1] === "status");
      return !diagnostic;
    }

    if (executable === "env") {
      index += 1;
      while (index < tokens.length) {
        const option = unquoteShellToken(tokens[index]);
        if (isShellAssignment(option)) {
          index += 1;
        } else if (option === "--") {
          index += 1;
          break;
        } else if (["-S", "--split-string"].includes(option)) {
          const splitCommand = unquoteShellToken(tokens[index + 1]);
          return Boolean(splitCommand) && shellRunsTarget(splitCommand, target);
        } else if (optionNeedsValue(option, ["-u", "-C"], ["--unset", "--chdir"])) {
          index += 2;
        } else if (option.startsWith("-")) {
          index += 1;
        } else {
          break;
        }
      }
      wrapperCount += 1;
      continue;
    }

    if (executable === "sudo") {
      index += 1;
      const valueOptions = ["-u", "-g", "-h", "-p", "-C", "-T", "-R", "-r", "-t"];
      const longValueOptions = [
        "--user", "--group", "--host", "--prompt", "--chdir", "--command-timeout",
        "--chroot", "--role", "--type", "--close-from",
      ];
      while (index < tokens.length) {
        const option = unquoteShellToken(tokens[index]);
        if (option === "--") {
          index += 1;
          break;
        }
        if (optionNeedsValue(option, valueOptions, longValueOptions)) {
          index += 2;
        } else if (option.startsWith("-")) {
          index += 1;
        } else {
          break;
        }
      }
      wrapperCount += 1;
      continue;
    }

    if (["command", "exec", "nohup"].includes(executable)) {
      index += 1;
      while (index < tokens.length) {
        const option = unquoteShellToken(tokens[index]);
        if (executable === "command" && ["-v", "-V"].includes(option)) {
          return false;
        }
        if (executable === "exec" && optionNeedsValue(option, ["-a"], [])) {
          index += 2;
        } else if (option === "--" || option.startsWith("-")) {
          index += 1;
        } else {
          break;
        }
      }
      wrapperCount += 1;
      continue;
    }

    if (executable === "eval") {
      return shellRunsTarget(tokens.slice(index + 1).map(unquoteShellToken).join(" "), target);
    }

    if (executable === "rg") {
      return tokens.slice(index + 1).some((token, offset) => {
        const option = unquoteShellToken(token);
        const pre = option === "--pre" ? unquoteShellToken(tokens[index + offset + 2])
          : option.startsWith("--pre=") ? unquoteShellToken(option.slice(6)) : "";
        return pre && shellRunsTarget(pre, target);
      });
    }
    if (executable === "sed") {
      if (target === "launcher" && tokens.some((token) => /^-(?:[^-]*i|\-in-place)(?:=|$)/.test(unquoteShellToken(token)))
          && tokens.some((token) => shellBasename(token) === "codex-with-cc-launch")) return true;
      return tokens.slice(index + 1).some((token) => {
        const script = unquoteShellToken(token).match(/^(?:[\d,$]+)?e\s+(.+)$/);
        return script && shellRunsTarget(script[1], target);
      });
    }

    if (["sh", "bash", "zsh"].includes(executable)) {
      for (let optionIndex = index + 1; optionIndex < tokens.length; optionIndex += 1) {
        const option = unquoteShellToken(tokens[optionIndex]);
        if (/^-[^-]*c/.test(option)) {
          const nestedCommand = unquoteShellToken(tokens[optionIndex + 1]);
          return Boolean(nestedCommand) && shellRunsTarget(nestedCommand, target);
        }
        if (!option.startsWith("-")) {
          break;
        }
      }
    }
    if (["delegate", "launcher"].includes(target) && ["python", "python3", "pwsh", "powershell", "sh", "bash", "zsh"].includes(executable)) {
      return tokens.slice(index + 1).some((token) => !unquoteShellToken(token).startsWith("-")
        && (target === "launcher" ? shellBasename(token) === "codex-with-cc-launch"
          : DELEGATE_ENTRYPOINT_PATTERNS.some((pattern) => pattern.test(unquoteShellToken(token)))));
    }
    return false;
  }
  return false;
}

// A command-shape guard, not a shell parser or a sandbox. Heredoc data and
// quoted prose are not executable positions. Interpreted/dynamic code still
// requires runtime permissions; these checks only recognize visible execution.
function commandSubstitutions(source, heredocData = false) {
  const commands = [];
  let quote = "";
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    if (char === "\\" && quote !== "'") { i += 1; continue; }
    if (!heredocData && char === "'" && quote !== '"') { quote = quote === "'" ? "" : "'"; continue; }
    if (!heredocData && char === '"' && quote !== "'") { quote = quote === '"' ? "" : '"'; continue; }
    if (quote === "'") continue;
    if (char === "`") {
      let end = i + 1;
      while (end < source.length && source[end] !== "`") {
        if (source[end] === "\\") end += 1;
        end += 1;
      }
      commands.push(source.slice(i + 1, end));
      i = end;
    } else if (["$(", "<(", ">("].includes(source.slice(i, i + 2))) {
      let end = i + 2;
      let depth = 1;
      let innerQuote = "";
      for (; end < source.length; end += 1) {
        const inner = source[end];
        if (inner === "\\" && innerQuote !== "'") { end += 1; continue; }
        if ((inner === "'" || inner === '"') && (!innerQuote || innerQuote === inner)) {
          innerQuote = innerQuote ? "" : inner; continue;
        }
        if (!innerQuote && inner === "(") depth += 1;
        if (!innerQuote && inner === ")" && --depth === 0) break;
      }
      commands.push(source.slice(i + 2, end));
      i = end;
    }
  }
  return commands;
}

function executableShellSources(command) {
  const lines = String(command || "").split("\n");
  const shell = [];
  const additional = [];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    // Literal delimiters cover normal shell/Python/file-writing heredocs.
    const documents = [...line.matchAll(/<<(-)?\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))/g)]
      .filter((match) => {
        let quote = "";
        for (let index = 0; index < match.index; index += 1) {
          const char = line[index];
          if (char === "\\" && quote !== "'") { index += 1; continue; }
          if ((char === "'" || char === '"') && (!quote || quote === char)) quote = quote ? "" : char;
        }
        return !quote;
      });
    shell.push(line);
    for (const document of documents) {
      const delimiter = document[2] || document[3] || document[4];
      const body = [];
      while (++i < lines.length && (document[1] ? lines[i].replace(/^\t+/, "") : lines[i]) !== delimiter) body.push(lines[i]);
      const text = body.join("\n");
      const segments = shellCommandSegments(line);
      if (segments.some((tokens) => shellSegmentRunsTarget(tokens, "shell"))) additional.push(text);
      else if (segments.some((tokens) => shellSegmentRunsTarget(tokens, "interpreter"))) {
        // Obvious interpreter process calls stay blocked; ordinary write_text,
        // Markdown strings and shutil.copy2 path data do not become commands.
        for (const call of text.matchAll(/(?:subprocess\.(?:run|call|Popen|check_call|check_output)|os\.(?:system|popen)|(?:exec|execSync|spawn|spawnSync))\s*\(\s*(?:\[\s*)?(['"])(.*?)\1/g)) {
          additional.push(call[2]);
        }
      }
      if (document[4]) additional.push(...commandSubstitutions(text, true));
    }
  }
  return [shell.join("\n"), ...additional];
}

function shellRunsTarget(command, target, depth = 0) {
  if (depth > 16) return false;
  return executableShellSources(command).some((source) => {
    const segments = shellCommandSegments(source);
    const scriptPipe = target === "launcher" && launcherPipedToShell(source);
    return scriptPipe || segments.some((tokens) => shellSegmentRunsTarget(tokens, target))
      || commandSubstitutions(source).some((nested) => shellRunsTarget(nested, target, depth + 1));
  });
}

function launcherPipedToShell(source) {
  let current = [];
  let launcherInput = false;
  for (const token of [...tokenizeShell(source), ";"]) {
    if (/^(?:&&|\|\||[;&|]|\n|\r)$/.test(token)) {
      if (launcherInput && shellSegmentRunsTarget(current, "shell")) return true;
      launcherInput = token === "|" && (launcherInput
        || current.some((item) => shellBasename(item) === "codex-with-cc-launch"));
      current = [];
    } else current.push(token);
  }
  return false;
}

function hasDirectClaudeShellCommand(command) {
  return shellRunsTarget(command, "claude");
}

function hasDirectClaudeCommand(serialized) {
  const prefix = String.raw`(?:(?:(?:env|command|exec|nohup|sudo)(?:\s+-[^\s;&|]+)*|[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|[^\s;&|]+))\s+)*`;
  const executable = String.raw`(?:\.\/|\.\\|[\w:/\\.-]*[/\\])?claude(?:\.cmd|\.exe)?`;
  const boundary = String.raw`(?:\s+(?:-|--|<|>|2>|&>|;|\||&&|\|\|)|\s*$|$)`;
  return hasDirectClaudeShellCommand(serialized)
    || new RegExp(String.raw`(?:^|[\n\r;&|` + "`" + String.raw`"'])\s*${prefix}${executable}${boundary}`, "i").test(serialized);
}

function hasExplicitModel(payload) {
  const value = prop(payload, "model", "model");
  return value !== undefined && value !== null && String(value).trim() !== "";
}

function modelRequirementReason() {
  if (REQUIRED_MODEL_POLICY === "inherit_parent") {
    return "model must inherit from the main thread; omit explicit model override";
  }
  return `model must be ${REQUIRED_MODEL}`;
}

function preparedRoute(payload) {
  const message = String(payload.message || payload.prompt || "");
  const match = message.match(/^WorkflowPlan:\s*(.+)$/m);
  if (!match) return null;
  const planPath = path.resolve(match[1].trim());
  const raw = fs.readFileSync(planPath);
  const plan = JSON.parse(raw);
  const workflow = JSON.parse(fs.readFileSync(path.join(plan.artifactRoot, `workflow_${plan.workflowId}.json`), "utf8"));
  const pinned = workflow.preparedTasks?.[plan.planId];
  if (pinned?.status === "cancelled" || pinned?.cancellation) {
    throw new Error("prepared workflow plan was cancelled; prepare a fresh plan before dispatch");
  }
  if (plan.schemaVersion !== 1 || !["claude-code", "claude-process", "codex-native"].includes(plan.backend)
      || pinned?.path !== planPath || pinned?.sha256 !== createHash("sha256").update(raw).digest("hex")
      || JSON.stringify(plan.executionPolicy) !== JSON.stringify(workflow.executionPolicy)
      || plan.taskSha256 !== createHash("sha256").update(fs.readFileSync(plan.taskFile)).digest("hex")) {
    throw new Error("prepared workflow plan is changed or unregistered");
  }
  if (workflow.executionPolicy?.dispatch) {
    const receipt = pinned?.admission;
    const receiptPath = path.join(path.dirname(planPath), "admission.json");
    if (!receipt || receipt.path !== receiptPath || !fs.existsSync(receiptPath)
        || receipt.sha256 !== createHash("sha256").update(fs.readFileSync(receiptPath)).digest("hex")) {
      throw new Error("prepared plan needs admit-task before dispatch");
    }
  }
  return plan;
}

function validateWorkflowPayload(payload, toolName = "") {
  const serialized = stringify(payload);
  const problems = [];
  let route = null;
  try { route = preparedRoute(payload); } catch (error) { problems.push(String(error.message)); }
  const opaque = isOpaqueCollaborationSpawn(toolName, payload);

  if (route) {
    if (route.backend === "claude-process") problems.push("claude-process uses the main-thread fixed launcher, not spawn_agent");
    if (payload.model !== route.model) problems.push("model must match the prepared workflow plan");
  } else if (!opaque && REQUIRED_MODEL_POLICY === "inherit_parent") {
    if (hasExplicitModel(payload)) {
      problems.push(modelRequirementReason());
    }
  } else if (!opaque && REQUIRED_MODEL_POLICY !== "inherit_parent" && prop(payload, "model", "model") !== REQUIRED_MODEL) {
    problems.push(modelRequirementReason());
  }
  const effort = prop(payload, "reasoning_effort", "reasoningEffort");
  if (route) {
    if (effort !== route.reasoningEffort) problems.push("reasoning_effort must match the prepared workflow plan");
  } else if (!opaque && REQUIRED_EFFORT_POLICY === "inherit_parent") {
    if (effort !== undefined && effort !== null && String(effort).trim()) {
      problems.push("reasoning_effort must inherit from the main thread; omit explicit override");
    }
  } else if (!opaque && REQUIRED_EFFORT_POLICY !== "inherit_parent" && effort !== REQUIRED_EFFORT) {
    problems.push(`reasoning_effort must be ${REQUIRED_EFFORT}`);
  }
  const forkContext = prop(payload, "fork_context", "forkContext");
  if (forkContext !== undefined && !isFalse(forkContext)) {
    problems.push("fork_context: false is required");
  }
  const forkTurns = prop(payload, "fork_turns", "forkTurns");
  if (route && forkContext === undefined && forkTurns === undefined) {
    problems.push("prepared routes require explicit fork_context: false or fork_turns: none");
  }
  if (forkTurns !== undefined && String(forkTurns).toLowerCase() !== REQUIRED_FORK_TURNS) {
    problems.push(`fork_turns: "${REQUIRED_FORK_TURNS}" is required`);
  }

  // Codex 0.145+ encrypts collaboration child prompts before PreToolUse.
  // The hook can still enforce spawn metadata, while runtime artifacts prove
  // the child marker, delegate invocation, task metadata, and lifecycle.
  if (opaque) {
    return problems;
  }

  if (route) return problems;

  if (hasDirectClaudeCommand(serialized)) {
    problems.push("direct Claude CLI execution is forbidden");
  }
  if (hasFixedLauncherSpawnReference(serialized)) {
    return problems;
  }
  if (!hasChildMarker(serialized)) {
    problems.push("CODEX_CLAUDE_CHILD_THREAD=1 is required");
  }
  if (!hasDelegateEntrypoint(serialized)) {
    problems.push("delegate_to_claude.* is required");
  }
  if (!hasTaskFile(serialized)) {
    problems.push("-TaskFile is required");
  }
  if (hasLegacyInlineTask(serialized)) {
    problems.push("legacy inline -Task is forbidden; use -TaskFile");
  }
  if (!hasWorkflowId(serialized) && !prop(payload, "workflow_id", "workflowId")) {
    problems.push("-WorkflowId is required");
  }
  if (!hasTaskId(serialized) && !prop(payload, "task_id", "taskId")) {
    problems.push("-TaskId is required");
  }
  if (!hasSessionKey(serialized) && !prop(payload, "session_key", "sessionKey")) {
    problems.push("-SessionKey is required");
  }
  const role = String(prop(payload, "role", "role") || roleValue(serialized) || "").toLowerCase();
  if (!hasRole(serialized) && !role) {
    problems.push("-Role is required");
  } else if (!ALLOWED_ROLES.has(role)) {
    problems.push(`-Role must be one of ${Array.from(ALLOWED_ROLES).join(", ")}`);
  }
  if (role === "reviewer" && (!hasReviewForTaskId(serialized) || !hasReviewForRunId(serialized) || !hasReviewKind(serialized))) {
    problems.push("reviewer runs require -ReviewForTaskId, -ReviewForRunId, and -ReviewKind");
  }
  if (hasLegacyMode(serialized)) {
    problems.push("legacy -Mode is forbidden; use -Role");
  }
  if (hasAllowParallel(serialized) && !hasScope(serialized)) {
    problems.push("-Scope is required when -AllowParallel is used");
  }
  if (hasForbiddenEffort(serialized)) {
    problems.push("delegate_to_claude.* must not pass --effort");
  }

  return problems;
}

function handlePreToolUse(input) {
  const toolName = getToolName(input);
  const toolInput = getToolInput(input);
  const serialized = stringify(toolInput);
  const normalizedToolName = toolName.toLowerCase();

  const nestedProblems = [];
  for (const item of nestedToolUses(toolInput)) {
    const name = nestedToolName(item);
    if (!isWorkflowSpawnToolName(name)) {
      continue;
    }
    const problems = validateWorkflowPayload(nestedToolInput(item), name);
    if (problems.length > 0) {
      nestedProblems.push(`nested ${name}: ${problems.join("; ")}`);
    }
  }
  if (nestedProblems.length > 0) {
    writeJson(deny(`codex-with-cc platform gate blocked ${nestedProblems.join("; ")}.`));
    return;
  }

  if (isShellToolName(normalizedToolName)) {
    const problems = [];
    const shellCommand = String(getShellCommand(toolInput) || "");

    if (hasDirectClaudeShellCommand(shellCommand)) {
      problems.push("direct Claude CLI execution is forbidden");
    }

    if (isFixedLauncherShellCommand(shellCommand)) {
      try {
        const directory = path.resolve(toolInput.workdir || toolInput.cwd || input.cwd || process.cwd());
        const descriptor = JSON.parse(readOptionalText(path.join(directory, "launch.json")) || "null");
        const plan = JSON.parse(readOptionalText(path.join(directory, "plan.json")) || "null");
        if (descriptor?.invocation === "codex_with_cc_process" || plan?.backend === "claude-process") {
          const validation = spawnSync("python3", [path.join(pluginRoot(), "skills", "codex-with-cc", "scripts", "runtime.py"),
            "validate-process-launch", "-LaunchDirectory", directory], { encoding: "utf8", timeout: 3500, maxBuffer: 65536 });
          if (validation.error || validation.status !== 0) {
            problems.push("claude-process requires a valid immutable plan, admitted launch and original main-host identity");
          }
        }
      } catch {
        problems.push("fixed launcher descriptor or prepared plan is unreadable or invalid");
      }
    } else if (shellRunsTarget(shellCommand, "launcher")) {
      problems.push("codex-with-cc-launch must take no arguments and use a stable command shape; in-place launcher edits are also blocked");
    } else if (shellRunsTarget(shellCommand, "delegate")) {
      if (!hasChildMarker(serialized)) {
        problems.push("CODEX_CLAUDE_CHILD_THREAD=1 is required");
      }
      if (!hasTaskFile(serialized)) {
        problems.push("-TaskFile is required");
      }
      if (hasLegacyInlineTask(serialized)) {
        problems.push("legacy inline -Task is forbidden; use -TaskFile");
      }
      if (!hasWorkflowId(serialized)) {
        problems.push("-WorkflowId is required");
      }
      if (!hasTaskId(serialized)) {
        problems.push("-TaskId is required");
      }
      if (!hasSessionKey(serialized)) {
        problems.push("-SessionKey is required");
      }
      if (!hasRole(serialized)) {
        problems.push("-Role is required");
      } else if (!ALLOWED_ROLES.has(roleValue(serialized))) {
        problems.push(`-Role must be one of ${Array.from(ALLOWED_ROLES).join(", ")}`);
      }
      if (roleValue(serialized) === "reviewer" && (!hasReviewForTaskId(serialized) || !hasReviewForRunId(serialized) || !hasReviewKind(serialized))) {
        problems.push("reviewer runs require -ReviewForTaskId, -ReviewForRunId, and -ReviewKind");
      }
      if (hasLegacyMode(serialized)) {
        problems.push("legacy -Mode is forbidden; use -Role");
      }
      if (hasAllowParallel(serialized) && !hasScope(serialized)) {
        problems.push("-Scope is required when -AllowParallel is used");
      }
      if (hasForbiddenEffort(serialized)) {
        problems.push("delegate_to_claude.* must not pass --effort");
      }
    }

    if (problems.length > 0) {
      writeJson(deny(`codex-with-cc platform gate blocked Bash: ${problems.join("; ")}.`));
    }
    return;
  }

  if (!isWorkflowSpawnToolName(toolName)) {
    return;
  }

  const problems = validateWorkflowPayload(toolInput, toolName);
  if (problems.length > 0) {
    writeJson(deny(`codex-with-cc platform gate blocked ${toolName}: ${problems.join("; ")}.`));
  }
}

const input = parseInput(await readStdin());
const eventName = getEventName(input);

if (eventName === "SessionStart") {
  writeJson(additionalContext("SessionStart"));
} else if (eventName === "UserPromptSubmit") {
  if (containsSubagentTrigger(getPrompt(input))) {
    writeJson(additionalContext("UserPromptSubmit"));
  }
} else if (eventName === "PreToolUse") {
  handlePreToolUse(input);
}
