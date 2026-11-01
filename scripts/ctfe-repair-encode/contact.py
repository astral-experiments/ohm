"""Read the unscored, source-bound native repair and locate every Cargo product."""

import ast
import hashlib
import json
import re
from pathlib import Path
from collections import Counter

from evidence import WILD, need

REG = json.loads(Path(__file__).with_name("owners.json").read_bytes())
ROLES = {"cargo": "bin/cargo", "rustc": "bin/rustc", "wild": WILD}
AUX = ("/usr/bin/cc", "/usr/libexec/gcc/x86_64-linux-gnu/13/collect2")
ORDER = ("O", "P", "B")
OLD_BOOTS = {x["boot"] for x in REG["originals"]} | {
    "4f4d4a31-68c1-447b-9909-8f4c951d6d82",
    "c9fb2eab-3d98-4154-b864-cfac6df82005",
    "c652a1a6-da1c-4698-b416-cd02e2b88e9a",
    "5d0531b9-cfc3-4e08-878a-6c03ee6d2b7f",
}


def launch(mode, where, sdk, command):
    need(mode in ORDER and where.is_absolute() and sdk.is_absolute(), "unbound repair")
    prefix = [str(where.parents[2] / "repair-kernel-tools/observe"), str(where / "positive.tsv"), "--"]
    if mode != "O":
        calls = where / "calls"
        prefix += [
            str(where.parents[1] / "tools/table-notify"),
            str(calls),
            str(sdk),
            str(calls / "notify.status"),
            "--",
        ]
    return prefix + command


def execs(data):
    """Read fixed -f exec-only strace: unresolved or opaque attempts cannot certify a roster."""
    pending = {}
    rows = []
    for line in data.splitlines():
        part = re.fullmatch(r"(\d+)\s+(.*)", line)
        need(part is not None, ("unframed trace", line[:100]))
        pid, text = int(part[1]), part[2]
        if text.startswith("<... execve resumed>"):
            need(pid in pending, "unmatched resumed exec")
            text = pending.pop(pid) + text.removeprefix("<... execve resumed>")
        elif not text.startswith("execve("):
            need(text.startswith("--- SIG") and text.endswith(" ---"), ("unclassified trace", text[:150]))
            continue
        else:
            need(pid not in pending, "two outstanding execs")
        if text.endswith("<unfinished ...>"):
            pending[pid] = text.removesuffix("<unfinished ...>").rstrip()
            continue
        if re.search(r"\)\s+= -1 [A-Z0-9_]+(?: \(.*\))?$", text):
            continue
        m = re.fullmatch(r'execve\(("(?:\\.|[^"])*"), (\[.*\]), .*\)\s+= 0', text)
        need(m is not None, ("unparsed exec", pid, text[:120]))
        exe, argv = map(ast.literal_eval, m.groups())
        need(
            exe.startswith("/") and isinstance(argv, list) and argv and all(type(v) is str for v in argv),
            "truncated or relative exec",
        )
        rows.append([pid, exe, argv])
    need(not pending and rows, "incomplete exec chronology")
    return rows


def topology(raw, sdk, proxy, command, units, *, captured=None, notifier=None):
    return topology_rows(execs(raw), sdk, proxy, command, units, captured=captured, notifier=notifier)


def topology_rows(rows, sdk, proxy, command, units, *, captured=None, notifier=None):
    paths = {str(sdk / file): name for name, file in ROLES.items()}
    image_rows = {}
    by_unit, cargo, wild = {}, [], []
    extras = Counter()
    proxies = []
    aux_outputs = []
    for pid, exe, argv in rows:
        role = paths.get(exe)
        if role is None:
            extras[exe] += 1
            if exe == str(proxy / "cargo"):
                need(argv == command, "wrong Cargo proxy command")
                proxies.append(pid)
            elif exe in AUX:
                need(argv.count("-o") == 1, "foreign system linker output")
                aux_outputs.append(argv[argv.index("-o") + 1])
            else:
                need(
                    notifier and exe == notifier[0] and argv == notifier,
                    ("unexpected successful executable", exe),
                )
            continue
        need(str(pid) not in image_rows, "registered PID re-executed")
        image_rows[str(pid)] = (role, argv)
        if role == "cargo":
            need(argv[1:] == command[2:], "wrong genuine Cargo command")
            cargo.append(pid)
        elif role == "rustc":
            need(
                argv.count("--crate-name") == argv.count("--crate-type") == 1
                and not any(
                    a.removeprefix("-Z").split("=", 1)[0] in ("link-only", "ohm-link-only") for a in argv
                ),
                "extra/query/link-only rustc",
            )
            unit = tuple(argv[argv.index(a) + 1] for a in ("--crate-name", "--crate-type"))
            need(unit not in by_unit, "extra actual compiler")
            by_unit[unit] = argv
        else:
            need(argv.count("-o") == 1, "extra Wild query or ambiguous output")
            wild.append(argv[argv.index("-o") + 1])
    need(
        sorted(map(list, by_unit)) == sorted(units) and len(cargo) == len(wild) == 1,
        "unexpected compiler/link roster",
    )
    need(
        extras == Counter([str(proxy / "cargo"), *AUX, *([notifier[0]] if notifier else [])])
        and proxies == cargo
        and aux_outputs == [wild[0], wild[0]],
        "changed actual GCC/Wild chain or rustup reexec",
    )
    if captured is not None:
        need(
            image_rows == {pid: (im["role"], im["argv"]) for pid, im in captured.items()},
            "exec and physical image/argv disagree",
        )
    return {"compilers": {k[0] + ":" + k[1]: v for k, v in sorted(by_unit.items())}, "wild_output": wild[0]}


def placement(messages, work, *, full=True):
    def rooted(value):
        p = Path(value)
        need(p.is_absolute() and p.as_posix() == value and ".." not in p.parts, "uncanonical Cargo product")
        rel = p.relative_to(work)
        need(
            len(rel.parts) > 1 and rel.parts[0] in {"target", "build"},
            "Cargo product beyond the enrolled roots",
        )
        return str(rel)

    artifacts, outputs = {}, []
    for m in messages:
        if m["reason"] == "compiler-artifact":
            key = json.dumps(
                [m["package_id"], m["target"], m["features"], m["profile"]],
                sort_keys=True,
                separators=(",", ":"),
            )
            need(key not in artifacts and m["filenames"], "duplicate unit or no emitted filename")
            artifacts[key] = [
                list(map(rooted, m["filenames"])),
                rooted(m["executable"]) if m["executable"] is not None else None,
            ]
        elif m["reason"] == "build-script-executed":
            outputs.append([m["package_id"], rooted(m["out_dir"])])
    if full:
        need(
            len(artifacts) == 375
            and sum(json.loads(k)[0].startswith("registry+") for k in artifacts) == 337
            and outputs,
            "incomplete historic Cargo placements",
        )
    return dict(artifacts=artifacts, build_script_out_dirs=sorted(outputs))


def digest(value):
    return hashlib.sha256(
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


def listener(calls, mode, sdk, paths, all_paths, inventory):
    import evidence as ev

    need(
        mode in ("P", "B")
        and (calls / "config").read_text() == ev.config(mode, paths)
        and (calls / "owners").read_text() == "".join(p + "\n" for p in all_paths),
        "changed notifier owner registration",
    )
    images, events = ev.physical(calls, sdk, paths, inventory=inventory, kernel=True)
    allowed = {"config", "owners", "driver.reference", "adopted", "notify.status"}
    for pid, im in images.items():
        stem = im["role"] + "-" + pid
        for k in (
            ("cmdline", "image", "maps", "mmap", "events")
            if im["role"] == "rustc"
            else ("cmdline", "image")
        ):
            allowed.add(stem + "." + k)
    need(allowed == {p.name for p in calls.iterdir()}, "missing/extra kernel evidence")
    rc, n, continued, injected, denied = map(int, (calls / "notify.status").read_text().strip().split("\t"))
    records = [e for rows in events.values() for e in rows]
    need(
        rc == 0
        and n == len(images)
        and continued > 0
        and injected == sum(x["fd"] >= 0 for x in records)
        and denied
        == sum(e["tag"] == "G" and e["error"] != 0 for e in records)
        == (len(paths) if mode == "B" else 0),
        "failure or incomplete ADDFD closure",
    )
    adopted = [line.split("\t") for line in (calls / "adopted").read_text().splitlines()]
    need(
        all(len(s) == 2 and int(s[0]) > 0 and int(s[1]) == 0 for s in adopted)
        and len({p for p, _ in adopted}) == len(adopted),
        "failed or duplicate adopted helper",
    )
    return images, events
