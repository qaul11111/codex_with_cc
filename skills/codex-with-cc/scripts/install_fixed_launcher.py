#!/usr/bin/env python3
"""Thin CLI wrapper around the consolidated install_launcher in fixed_launcher."""

from __future__ import annotations

import argparse

from codex_with_cc_runtime.fixed_launcher import install_launcher


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the codex-with-cc stable launcher.")
    parser.add_argument("--codex-home", help="Override $CODEX_HOME")
    args = parser.parse_args()
    launcher = install_launcher(args.codex_home)
    print(f"Installed {launcher}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
