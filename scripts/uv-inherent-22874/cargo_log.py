"""Verbatim readers from the real multiline #22619 Cargo transcript controls."""
import json,re,shlex
from core import guard as need

def cargo_running_commands(stderr):
    pending = []
    for line in stderr.decode().splitlines():
        begin = re.match(r"^[ \t]*Running `(.*)$", line)
        if begin:
            need(not pending, "unterminated Cargo command before next invocation")
            pending.append(begin[1])
        elif pending:
            pending.append(line)
        else:
            continue
        if not pending[-1].endswith("`"):
            continue
        try:
            args = shlex.split("\n".join(pending)[:-1])
        except ValueError:
            # A quoted multiline package description can itself end a line with a backtick.
            continue
        need(bool(args), "empty Cargo command")
        yield args
        pending.clear()
    need(not pending, "incomplete Cargo command")

def running_rustcs(stderr,rustc):
    cmds=[]
    for vals in cargo_running_commands(stderr):
        ids=[i for i,v in enumerate(vals) if v==str(rustc)]
        if not ids:continue
        need(len(ids)==1,"ambiguous rustc");args=vals[ids[0]:]
        if "--crate-name" in args:cmds.append(args)
    return cmds

def cargo_messages(data):
    from urllib.parse import unquote, urlsplit

    events = []
    scripts = set()
    printed = set()
    rows = data.splitlines()
    allowed = {"compiler-artifact", "compiler-message", "build-script-executed", "build-finished"}
    for line in rows:
        if line.startswith(b"{"):
            event = json.loads(line)
            need(isinstance(event, dict) and event.get("reason") in allowed, "unknown Cargo JSON record")
            events.append(event)
            if event["reason"] == "build-script-executed":
                source, fragment = event["package_id"].rsplit("#", 1)
                if "@" in fragment:
                    name, version = fragment.rsplit("@", 1)
                else:
                    name = unquote(urlsplit(source).path).rstrip("/").rsplit("/", 1)[-1]
                    version = fragment
                scripts.add((name, version))
        else:
            match = re.fullmatch(rb"\[([A-Za-z0-9_-]+) ([0-9A-Za-z.+-]+)\](?: .*)?", line)
            need(match is not None, "unexpected non-JSON Cargo stdout")
            printed.add((match[1].decode(), match[2].decode()))
    need(printed <= scripts, "verbose line has no matching Cargo build-script record")
    need(bool(events) and rows[-1].startswith(b"{") and sum(e["reason"] == "build-finished" for e in events) == 1,
         "missing or duplicate Cargo completion")
    need(events[-1].get("success") is True and events[-1]["reason"] == "build-finished", "typed completion")
    return events
