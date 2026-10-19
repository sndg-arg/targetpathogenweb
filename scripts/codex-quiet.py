#!/usr/bin/env python3
"""Run a command without injecting its full output into an AI context.

Works on Linux/macOS and native Windows: output goes straight to a log file
(no select() on pipes, which Windows lacks) and timeouts/limits kill the whole
process tree (killpg on POSIX, taskkill /T on Windows).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"

SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization:\s*(?:bearer|basic)\s+)\S+"),
    re.compile(
        r"""(?ix)
        ( ["']? (?:api[_-]?key|access[_-]?token|token|password|secret)
          ["']? \s* [=:] \s* ["']? )
        [^\s,"'}]+
        """
    ),
    re.compile(r"(://[^:/\s]+:)[^@\s]+(@)"),
)


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        replacement = r"\1[REDACTED]\2" if pattern.groups == 2 else r"\1[REDACTED]"
        text = pattern.sub(replacement, text)
    return text


def clean_old_logs(log_dir: Path, retention_hours: float) -> int:
    if retention_hours <= 0:
        return 0
    cutoff = time.time() - retention_hours * 3600
    removed = 0
    for path in log_dir.glob("codex-quiet-*.log"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def count_lines(path: Path) -> int:
    count = 0
    last = b""
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            count += chunk.count(b"\n")
            last = chunk[-1:]
    return count + (1 if path.stat().st_size and last != b"\n" else 0)


def stop_process_tree(process: subprocess.Popen[bytes], grace: float) -> None:
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=grace)
        except (OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def tail_text(path: Path, lines: int, chars: int) -> str:
    if lines <= 0 or chars <= 0:
        return ""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max(chars * 4, 8192)))
        data = stream.read().decode("utf-8", errors="replace")
    return redact("\n".join(data.splitlines()[-lines:])[-chars:])


def resolve_command(command: list[str]) -> list[str]:
    # Windows' CreateProcess doesn't apply PATHEXT, so `npm` wouldn't find npm.cmd.
    found = shutil.which(command[0])
    return [found, *command[1:]] if found else command


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture verbose output and emit only a compact JSON result."
    )
    parser.add_argument("--timeout", type=float, default=None, help="seconds")
    parser.add_argument("--error-lines", type=int, default=20)
    parser.add_argument("--max-error-chars", type=int, default=3000)
    parser.add_argument("--preview-lines", type=int, default=0)
    parser.add_argument("--max-preview-chars", type=int, default=1000)
    parser.add_argument(
        "--max-log-bytes",
        type=int,
        default=100 * 1024 * 1024,
        help="stop the command if its captured output exceeds this size",
    )
    parser.add_argument("--retention-hours", type=float, default=24)
    parser.add_argument("--kill-grace", type=float, default=2)
    parser.add_argument("--log-dir", default=tempfile.gettempdir())
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide a command after --")

    log_dir = Path(args.log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    removed_logs = clean_old_logs(log_dir, args.retention_hours)
    fd, raw_path = tempfile.mkstemp(prefix="codex-quiet-", suffix=".log", dir=log_dir)
    os.close(fd)
    log_path = Path(raw_path)
    started = time.monotonic()

    if IS_WINDOWS:
        group_kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        group_kwargs = {"start_new_session": True}

    timed_out = False
    output_limit_exceeded = False
    process: subprocess.Popen[bytes] | None = None
    try:
        with log_path.open("wb") as output:
            process = subprocess.Popen(
                resolve_command(command),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                **group_kwargs,
            )
            while process.poll() is None:
                if args.timeout is not None and time.monotonic() - started >= args.timeout:
                    timed_out = True
                    stop_process_tree(process, args.kill_grace)
                    break
                if (
                    args.max_log_bytes > 0
                    and os.fstat(output.fileno()).st_size > args.max_log_bytes
                ):
                    output_limit_exceeded = True
                    stop_process_tree(process, args.kill_grace)
                    break
                time.sleep(0.05)
        if output_limit_exceeded:
            with log_path.open("r+b") as output:
                output.truncate(args.max_log_bytes)
        if timed_out:
            code = 124
        elif output_limit_exceeded:
            code = 125
        else:
            code = process.returncode
    except OSError as exc:
        if process is not None:
            stop_process_tree(process, args.kill_grace)
        with log_path.open("ab") as output:
            output.write(f"launcher error: {exc}\n".encode())
        code = 127

    size = log_path.stat().st_size
    result: dict[str, object] = {
        "ok": code == 0,
        "exit_code": code,
        "seconds": round(time.monotonic() - started, 3),
        "bytes": size,
        "lines": count_lines(log_path),
        "log": str(log_path),
    }
    if removed_logs:
        result["old_logs_removed"] = removed_logs
    if timed_out:
        result["timed_out"] = True
    if output_limit_exceeded:
        result["output_limit_exceeded"] = True
        result["max_log_bytes"] = args.max_log_bytes
    if code != 0:
        result["error_tail"] = tail_text(log_path, args.error_lines, args.max_error_chars)
    elif args.preview_lines:
        result["preview"] = tail_text(log_path, args.preview_lines, args.max_preview_chars)

    # A Windows console's default codepage can't encode every log character.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
