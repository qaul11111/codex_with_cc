#!/usr/bin/env python3
"""Claude's supported PreToolUse JSON protocol; task-local and fail closed."""
import json
import sys
from pathlib import Path

from codex_with_cc_runtime.process_permissions import permission_hook

if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("One immutable plan path is required")
        print(json.dumps(permission_hook(Path(sys.argv[1]).resolve(), json.load(sys.stdin))))
    except Exception:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Prepared permission guard failed closed"}}))
