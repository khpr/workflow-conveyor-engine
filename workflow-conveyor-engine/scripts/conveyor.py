#!/usr/bin/env python3
"""workflow-conveyor-engine: minimal durable state machine for long-running WOs.

Design goals:
- single-file JSON state
- tick = run exactly one step
- safe-by-default fuse: backup then (optionally) restart
- optional notification hook (e.g. Telegram) on tick result

This is intentionally small and dependency-free.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_cmd(cmd: str) -> subprocess.CompletedProcess:
    # shell=False by default for safety; allow simple quoted commands
    argv = shlex.split(cmd)
    return subprocess.run(argv, text=True, capture_output=True)


def backup_files(backup_tar_gz: Path, files: List[Path]) -> None:
    backup_tar_gz.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(backup_tar_gz, "w:gz") as tf:
        for f in files:
            if f.exists():
                tf.add(str(f), arcname=f.name)


def cmd_init(args):
    state_path = Path(args.state)
    steps = json.loads(Path(args.steps_json).read_text(encoding="utf-8"))
    obj = {
        "flow": args.flow,
        "title": args.title,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "current_step": 0,
        "steps": steps,
        "history": [],
    }
    write_json_atomic(state_path, obj)
    print(json.dumps({"ok": True, "state": str(state_path)}, ensure_ascii=False))


def cmd_status(args):
    state = read_json(Path(args.state))
    cur = state.get("current_step", 0)
    steps = state.get("steps", [])
    done = cur >= len(steps)
    out = {
        "flow": state.get("flow"),
        "title": state.get("title"),
        "current_step": cur,
        "total_steps": len(steps),
        "done": done,
        "current": None if done else steps[cur],
        "updated_at": state.get("updated_at"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def maybe_notify(notify_cmd: Optional[str], payload: Dict[str, Any]) -> None:
    if not notify_cmd:
        return
    # Send JSON on stdin to an external notifier.
    try:
        subprocess.run(shlex.split(notify_cmd), input=json.dumps(payload, ensure_ascii=False), text=True)
    except Exception:
        # Never fail the conveyor because of notifications.
        pass


def cmd_tick(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    steps = state.get("steps", [])
    cur = int(state.get("current_step", 0))

    if cur >= len(steps):
        out = {"ok": True, "done": True, "message": "already complete"}
        print(json.dumps(out, ensure_ascii=False))
        maybe_notify(args.notify_cmd, {"event": "tick", "result": out, "state": state_path.name})
        return

    step = steps[cur]
    run = step.get("run")
    verify = step.get("verify")

    record = {
        "at": now_iso(),
        "step_index": cur,
        "step_id": step.get("id"),
        "title": step.get("title"),
        "run": run,
        "verify": verify,
        "ok": False,
        "stdout": "",
        "stderr": "",
        "verify_stdout": "",
        "verify_stderr": "",
        "exit_code": None,
        "verify_exit_code": None,
    }

    if not run or not isinstance(run, str):
        record["stderr"] = "missing step.run"
        state.setdefault("history", []).append(record)
        state["updated_at"] = now_iso()
        write_json_atomic(state_path, state)
        print(json.dumps({"ok": False, "error": "missing step.run"}, ensure_ascii=False))
        sys.exit(2)

    p = run_cmd(run)
    record["exit_code"] = p.returncode
    record["stdout"] = p.stdout
    record["stderr"] = p.stderr

    if p.returncode != 0:
        state.setdefault("history", []).append(record)
        state["updated_at"] = now_iso()
        write_json_atomic(state_path, state)
        out = {"ok": False, "step": step, "exit_code": p.returncode}
        print(json.dumps(out, ensure_ascii=False))
        maybe_notify(args.notify_cmd, {"event": "tick", "result": out, "state": state_path.name})
        sys.exit(p.returncode)

    if verify and isinstance(verify, str):
        v = run_cmd(verify)
        record["verify_exit_code"] = v.returncode
        record["verify_stdout"] = v.stdout
        record["verify_stderr"] = v.stderr
        if v.returncode != 0:
            state.setdefault("history", []).append(record)
            state["updated_at"] = now_iso()
            write_json_atomic(state_path, state)
            out = {"ok": False, "step": step, "verify_exit_code": v.returncode}
            print(json.dumps(out, ensure_ascii=False))
            maybe_notify(args.notify_cmd, {"event": "tick", "result": out, "state": state_path.name})
            sys.exit(v.returncode)

    # success
    record["ok"] = True
    state.setdefault("history", []).append(record)
    state["current_step"] = cur + 1
    state["updated_at"] = now_iso()
    write_json_atomic(state_path, state)
    out = {"ok": True, "advanced_to": cur + 1, "done": (cur + 1) >= len(steps)}
    print(json.dumps(out, ensure_ascii=False))
    maybe_notify(args.notify_cmd, {"event": "tick", "result": out, "state": state_path.name})


def cmd_fuse(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    flow = state.get("flow", "unknown")

    backup_dir = Path(args.backup_dir)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = backup_dir / "workflow-conveyor-engine" / str(flow) / f"{ts}.tar.gz"

    # minimal backup set
    files = [state_path]
    # Optional extras (best-effort)
    for extra in ["BOOT.md", "MEMORY.md"]:
        p = Path(os.getcwd()) / extra
        if p.exists():
            files.append(p)

    backup_files(out, files)

    resp = {
        "ok": True,
        "backup": str(out),
        "restart": None,
        "dry_run": bool(args.dry_run),
    }

    if args.dry_run:
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        return

    if not args.do_restart_cmd:
        resp["ok"] = False
        resp["error"] = "missing --do-restart-cmd"
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        sys.exit(2)

    p = run_cmd(args.do_restart_cmd)
    resp["restart"] = {
        "cmd": args.do_restart_cmd,
        "exit_code": p.returncode,
        "stdout": p.stdout,
        "stderr": p.stderr,
    }
    resp["ok"] = p.returncode == 0
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    sys.exit(p.returncode)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--flow", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--steps-json", required=True)
    p.add_argument("--state", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("status")
    p.add_argument("--state", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("tick")
    p.add_argument("--state", required=True)
    p.add_argument("--notify-cmd", required=False, help="Optional notifier command; JSON will be sent on stdin")
    p.set_defaults(func=cmd_tick)

    p = sub.add_parser("fuse")
    p.add_argument("--state", required=True)
    p.add_argument("--backup-dir", required=True)
    p.add_argument("--do-restart-cmd", required=False)
    p.add_argument("--dry-run", action="store_true", default=False)
    p.set_defaults(func=cmd_fuse)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
