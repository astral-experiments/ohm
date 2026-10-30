import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from study import need, sha


class ExecTrace:
    kind = "kernel-exec"

    def __init__(self):
        self.proc = subprocess.Popen(
            ["sudo", "-n", "/usr/bin/eslogger", "exec"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.groups = {}
        self.errors = []
        self.counter = None
        self.read = threading.Thread(target=self._read, daemon=True)
        self.read.start()

    def _read(self):
        decoder = json.JSONDecoder()
        pending = ""
        for line in self.proc.stdout:
            try:
                pending += line.decode()
                if not pending.strip():
                    pending = ""
                    continue
                try:
                    record, end = decoder.raw_decode(pending.lstrip())
                except json.JSONDecodeError:
                    need(len(pending) < 8 * 1024 * 1024, "oversized or invalid Endpoint Security event")
                    continue
                need(not pending.lstrip()[end:].strip(), "unsupported multi-event frame")
                pending = ""
                event = record["event"]["exec"]
                t = event["target"]
                group = t["group_id"]
                seq = record["seq_num"]
                need(isinstance(seq, int), "missing kernel sequence number")
                if self.counter is not None and seq != self.counter + 1:
                    self.errors.append("exec stream sequence discontinuity")
                self.counter = seq
                slot = self.groups.get(group)
                if slot is None:
                    slot = self.groups.get(t["session_id"])
                if slot is not None:
                    a = event["args"]
                    need(isinstance(a, list) and all(isinstance(v, str) for v in a), "unknown ES argv")
                    file = t["executable"]
                    slot.append(
                        {
                            "pid": t["audit_token"]["pid"],
                            "ppid": t["ppid"],
                            "pgid": group,
                            "path": file["path"],
                            "argv": a,
                            "seq": seq,
                            "cdhash": t.get("cdhash"),
                            **(slot.extra_event_fields(record,t) if hasattr(slot,"extra_event_fields") else {}),
                        }
                    )
            except (KeyError, TypeError, ValueError, RuntimeError) as e:
                self.errors.append(type(e).__name__ + ": " + str(e)[:150])
                pending = ""

    def command(self, argv, *, env, cwd, out, err, timeout=600, observed_rows=None):
        # Hold before the real exec so a fast child cannot beat group registration.
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(w)
                os.setsid()
                if os.read(r, 1) != b"1":
                    os._exit(122)
                os.close(r)
                os.chdir(cwd)
                os.dup2(out.fileno(), 1)
                os.dup2(err.fileno(), 2)
                os.execvpe(argv[0], argv, env)
            except BaseException:
                os._exit(123)
        os.close(r)
        rows = self.groups[pid] = [] if observed_rows is None else observed_rows
        os.write(w, b"1")
        os.close(w)
        expired = threading.Event()

        def kill():
            expired.set()
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        watchdog = threading.Timer(timeout, kill)
        watchdog.start()
        try:
            _, status = os.waitpid(pid, 0)
        finally:
            watchdog.cancel()
        # Deliver an ordered end marker with an ordinary successful exec in the same event stream.
        self._barrier()
        need(not self.errors and not expired.is_set(), f"untrusted native trace {self.errors[:2]}")
        self.groups.pop(pid)
        return os.waitstatus_to_exitcode(status), rows

    def _barrier(self, timeout=8):
        r, w = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(w)
            os.setsid()
            os.read(r, 1)
            os.close(r)
            os.execl("/usr/bin/true", "true")
        os.close(r)
        rows = self.groups[child] = []
        os.write(w, b"1")
        os.close(w)
        os.waitpid(child, 0)
        stop = time.monotonic() + timeout
        while not rows and time.monotonic() < stop and self.proc.poll() is None:
            time.sleep(0.02)
        self.groups.pop(child)
        need(
            len(rows) == 1 and rows[0]["pid"] == child and Path(rows[0]["path"]).name == "true",
            "macOS exec observation unavailable (check eslogger Full Disk Access and sudo)",
        )

    def ready(self):
        stop = time.monotonic() + 15
        while self.proc.poll() is None and time.monotonic() < stop:
            try:
                self._barrier(timeout=0.4)
                need(not self.errors, "unsupported Endpoint Security event schema")
                return
            except RuntimeError:
                continue
        reason = self.proc.stderr.read(2048).decode(errors="replace") if self.proc.poll() is not None else ""
        raise RuntimeError(
            f"eslogger sentinel unavailable: status={self.proc.poll()}, error={reason!r}, schema={self.errors[:2]}"
        )

    def close(self):
        if self.proc.poll() is None:
            subprocess.run(
                ["sudo", "-n", "/usr/bin/pkill", "-INT", "-g", str(self.proc.pid)], capture_output=True
            )
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    ["sudo", "-n", "/usr/bin/pkill", "-TERM", "-g", str(self.proc.pid)], capture_output=True
                )
        self.read.join(timeout=5)
