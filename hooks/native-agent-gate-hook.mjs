#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FALLBACK_CONTRACT = {
  spawn: { forkContext: false },
  workerRoles: ["planner", "implementer", "researcher", "reviewer", "final-verifier"],
  modelProfiles: {},
  triggerPatterns: [
    "child[- ]?agent",
    "sub[- ]?agent",
    "child[- ]?thread",
    "sub[- ]?thread",
    "delegat(?:e|ion|ing)",
    "worker[- ]?execution",
    "子代理|子线程|多代理|委派|派工|执行层",
  ],
  taskEnvelope: {
    startMarker: "[NATIVE_CODEX_AGENT_TASK]",
    endMarker: "[/NATIVE_CODEX_AGENT_TASK]",
    requiredFields: [
      "WorkflowId",
      "TaskId",
      "Role",
      "TaskFile",
      "Scope",
      "ModelProfile",
      "Writable",
      "Parallel",
      "DispatcherRole",
    ],
  },
};

function pluginRoot() {
  return process.env.CODEX_PLUGIN_ROOT
    || process.env.CLAUDE_PLUGIN_ROOT
    || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

function readContract() {
  try {
    const raw = fs.readFileSync(
      path.join(pluginRoot(), "skills", "codex-native-agents", "contract.json"),
      "utf8",
    );
    const contract = JSON.parse(raw);
    return {
      ...FALLBACK_CONTRACT,
      ...contract,
      spawn: { ...FALLBACK_CONTRACT.spawn, ...(contract.spawn || {}) },
      taskEnvelope: { ...FALLBACK_CONTRACT.taskEnvelope, ...(contract.taskEnvelope || {}) },
      workerRoles: Array.isArray(contract.workerRoles)
        ? contract.workerRoles
        : FALLBACK_CONTRACT.workerRoles,
      modelProfiles: contract.modelProfiles || FALLBACK_CONTRACT.modelProfiles,
      triggerPatterns: Array.isArray(contract.triggerPatterns)
        ? contract.triggerPatterns
        : FALLBACK_CONTRACT.triggerPatterns,
    };
  } catch {
    return FALLBACK_CONTRACT;
  }
}

const CONTRACT = readContract();
const TRIGGER_PATTERNS = CONTRACT.triggerPatterns.map((pattern) => new RegExp(pattern, "i"));
const WORKER_ROLES = new Set(CONTRACT.workerRoles.map((role) => String(role)));
const MODEL_PROFILES = new Set(Object.keys(CONTRACT.modelProfiles));

const CONTEXT = [
  "Native Codex agent gate:",
  "- Dispatch only spawn_agent calls with fork_context: false and a full [NATIVE_CODEX_AGENT_TASK] envelope.",
  "- The envelope must name WorkflowId, TaskId, Role, TaskFile, Scope, ModelProfile, Writable, Parallel, and DispatcherRole: main.",
  "- Workers must not call spawn_agent or dispatch nested workers; return the structured report to the main thread.",
  "- Model overrides are optional; omit model to inherit the parent model.",
].join("\n");

function readStdin() {
  return new Promise((resolve) => {
    let input = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      input += chunk;
    });
    process.stdin.on("end", () => resolve(input));
  });
}

function parseInput(text) {
  try {
    return text.trim() ? JSON.parse(text) : {};
  } catch {
    return {};
  }
}

function writeJson(value) {
  process.stdout.write(JSON.stringify(value));
}

function eventName(input) {
  return input.hook_event_name || input.hookEventName || input.eventName || "";
}

function toolName(input) {
  return input.tool_name || input.toolName || "";
}

function toolInput(input) {
  return input.tool_input || input.toolInput || {};
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

function textItems(input) {
  if (!Array.isArray(input?.items)) {
    return [];
  }
  return input.items
    .filter((item) => item?.type === "text" && typeof item.text === "string")
    .map((item) => item.text);
}

function dispatchText(input) {
  const message = typeof input?.message === "string" ? input.message : "";
  return [message, ...textItems(input)].filter(Boolean).join("\n");
}

function promptText(input) {
  const prompt = input.prompt || input.user_prompt || input.userPrompt || "";
  return typeof prompt === "string" ? prompt : "";
}

function toolNameTail(name) {
  const parts = String(name).toLowerCase().split(/(?:__|[.:/\\])+/).filter(Boolean);
  return parts.at(-1) || "";
}

function isSpawnTool(name) {
  return toolNameTail(name) === "spawn_agent";
}

function isShellTool(name) {
  const normalized = String(name).toLowerCase();
  const tail = toolNameTail(name);
  return normalized === "bash" || tail === "shell_command" || tail === "exec_command";
}

function parseEnvelope(text) {
  const { startMarker, endMarker } = CONTRACT.taskEnvelope;
  const start = text.indexOf(startMarker);
  if (start === -1) {
    return null;
  }
  const bodyStart = start + startMarker.length;
  const end = text.indexOf(endMarker, bodyStart);
  if (end === -1) {
    return null;
  }

  const fields = {};
  for (const line of text.slice(bodyStart, end).split(/\r?\n/)) {
    const match = line.match(/^\s*([^:\n]+):\s*(.*?)\s*$/);
    if (match) {
      fields[match[1]] = match[2];
    }
  }
  return fields;
}

function validateSpawn(input) {
  const problems = [];
  const envelope = parseEnvelope(dispatchText(input));
  if (!envelope) {
    problems.push("native task envelope is required");
  } else {
    for (const field of CONTRACT.taskEnvelope.requiredFields) {
      if (!String(envelope[field] || "").trim()) {
        problems.push(`${field} is required in the native task envelope`);
      }
    }
    if (envelope.DispatcherRole && envelope.DispatcherRole !== "main") {
      problems.push("DispatcherRole: main is required");
    }
    if (envelope.Role && !WORKER_ROLES.has(envelope.Role)) {
      problems.push(`Role must be one of ${Array.from(WORKER_ROLES).join(", ")}`);
    }
    if (envelope.ModelProfile && MODEL_PROFILES.size > 0 && !MODEL_PROFILES.has(envelope.ModelProfile)) {
      problems.push(`ModelProfile must be one of ${Array.from(MODEL_PROFILES).join(", ")}`);
    }
  }
  if (prop(input, "fork_context", "forkContext") !== false) {
    problems.push("fork_context: false is required");
  }
  return problems;
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

function additionalContext(name) {
  return {
    hookSpecificOutput: {
      hookEventName: name,
      additionalContext: CONTEXT,
    },
  };
}

function shellSegments(command) {
  return String(command).split(/(?:&&|\|\||;|\n)/).map((segment) => segment.trim());
}

function unwrapCommandPosition(segment) {
  let remaining = segment.trim();
  while (remaining) {
    const commandWrapper = remaining.match(/^command\s+/i);
    if (commandWrapper) {
      remaining = remaining.slice(commandWrapper[0].length).trimStart();
      continue;
    }
    const envWrapper = remaining.match(/^env\s+(?:(?:[A-Za-z_]\w*)=(?:\S+)\s+)*/i);
    if (envWrapper && envWrapper[0].trim() !== "env") {
      remaining = remaining.slice(envWrapper[0].length).trimStart();
      continue;
    }
    const assignment = remaining.match(/^(?:[A-Za-z_]\w*)=(?:\S+)\s+/);
    if (assignment) {
      remaining = remaining.slice(assignment[0].length).trimStart();
      continue;
    }
    break;
  }
  return remaining;
}

function shellCommandBody(segment) {
  const match = unwrapCommandPosition(segment).match(
    /^(?:bash|sh|zsh)\s+(?:-[A-Za-z]*c\s+)(["'])([\s\S]*?)\1\s*$/i,
  );
  return match?.[2] || "";
}

function legacyExecutable(segment) {
  const command = unwrapCommandPosition(segment);
  const match = command.match(
    /^(?:[\w./:-]*[\\/])?(claude(?:\.(?:cmd|exe))?|delegate_to_claude(?:\.[A-Za-z0-9]+)?)(?=\s|$)/i,
  );
  return match?.[1] || "";
}

function legacyShellProblem(command) {
  for (const segment of shellSegments(command)) {
    const executable = legacyExecutable(segment) || legacyExecutable(shellCommandBody(segment));
    if (executable) {
      return executable.toLowerCase().startsWith("claude")
        ? "direct claude execution is forbidden"
        : "delegate_to_claude execution is forbidden";
    }
  }
  return "";
}

function hasDelegationIntent(prompt) {
  const text = String(prompt);
  const englishAction = /\b(?:delegate|dispatch|start|spawn|launch)\b/i;
  const englishWorker = /\b(?:subagents?|child\s+agents?|workers?)\b/i;
  const chineseIntent = /(?:开启|启动|安排|委派|派遣|分配).{0,20}(?:子代理|子线程|工作者|workers?)/;
  return (englishAction.test(text) && englishWorker.test(text)) || chineseIntent.test(text);
}

function nestedToolUses(input) {
  return Array.isArray(input?.tool_uses)
    ? input.tool_uses
    : Array.isArray(input?.toolUses)
      ? input.toolUses
      : [];
}

function handlePreToolUse(input) {
  const name = toolName(input);
  const payload = toolInput(input);

  if (isShellTool(name)) {
    const problem = legacyShellProblem(prop(payload, "command", "command") || "");
    if (problem) {
      writeJson(deny(`native agent gate blocked ${name}: ${problem}.`));
    }
    return;
  }

  if (isSpawnTool(name)) {
    const problems = validateSpawn(payload);
    if (problems.length > 0) {
      writeJson(deny(`native agent gate blocked ${name}: ${problems.join("; ")}.`));
    }
    return;
  }

  for (const item of nestedToolUses(payload)) {
    const nestedName = item?.recipient_name || item?.recipientName || item?.tool_name || item?.toolName || "";
    if (!isSpawnTool(nestedName)) {
      continue;
    }
    const nestedInput = item?.parameters || item?.tool_input || item?.toolInput || {};
    const problems = validateSpawn(nestedInput);
    if (problems.length > 0) {
      writeJson(deny(`native agent gate blocked nested ${nestedName}: ${problems.join("; ")}.`));
      return;
    }
  }
}

const input = parseInput(await readStdin());
const name = eventName(input);

if (name === "SessionStart") {
  writeJson(additionalContext(name));
} else if (name === "UserPromptSubmit") {
  if (hasDelegationIntent(promptText(input))) {
    writeJson(additionalContext(name));
  }
} else if (name === "PreToolUse") {
  handlePreToolUse(input);
}
