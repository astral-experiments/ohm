"""Keep the kernel's complete successful exec argv, separately from every hardware clock."""

import ast
import gzip
import hashlib
import json
import re
from pathlib import Path

from bindings import PROXIES, SDK, WILD, need

START = re.compile(r"^([0-9]+)\s+(execve\(.*)")
RESUME = re.compile(r"^([0-9]+)\s+<\.\.\. execve resumed>(.*)")
SUCCESS = re.compile(r'^execve\(("(?:\\.|[^"])*"), (\[.*\]), .*\)\s+= 0$')


def execs(lines):
    pending = {}
    rows = []
    for raw in lines:
        raw = raw.rstrip("\n")
        resumed = RESUME.match(raw)
        start = START.match(raw)
        if resumed:
            pid = int(resumed[1])
            need(pid in pending, ("orphan resumed exec", pid))
            text = pending.pop(pid) + resumed[2]
        elif start:
            pid = int(start[1])
            text = start[2]
            need(pid not in pending, ("second unresolved exec", pid))
        else:
            need(
                not re.search(r"\bexecve(?:at)?(?:\(| resumed>)", raw), ("unparsed exec", raw[:180])
            )
            continue
        if text.endswith("<unfinished ...>"):
            need(pid not in pending, ("duplicate unfinished exec", pid))
            pending[pid] = text.removesuffix("<unfinished ...>").rstrip()
            continue
        if re.search(r"\)\s+= -1 [A-Z0-9]+(?: \(.*\))?$", text):
            continue
        match = SUCCESS.fullmatch(text)
        need(match is not None, ("incomplete or unexpected exec", pid, text[:170], text[-55:]))
        path = ast.literal_eval(match[1])
        argv = ast.literal_eval(match[2])
        need(
            isinstance(argv, list) and argv and all(type(v) is str for v in argv),
            "truncated or non-string argv",
        )
        rows.append((pid, path, argv))
    need(not pending, ("orphan unfinished exec", list(pending)))
    return rows


def other_link(exe, argv):
    if "-o" in argv:
        out = argv[argv.index("-o") + 1]
        need(
            Path(out).name.startswith("conftest")
            and not any(x.endswith((".rlib", ".rcgu.o")) or x.startswith("@") for x in argv),
            ("unexpected real system link", exe, out),
        )
        return "configure C executable", out
    if set(argv[1:]) and set(argv[1:]) <= {"-v", "--version", "--help", "--print-output-format"}:
        return "query", None
    # GCC's GNU configure feature probe also produces the default a.out. The sealed original
    # has this exact complete argv in each of its three cold arms, except two GCC temp stems.
    normalized = [re.sub(r"/tmp/cc[A-Za-z0-9]+\.(o|res)", r"/tmp/cc-TEMP.\1", x) for x in argv]
    observed = hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()
    need(
        exe == "/usr/bin/ld"
        and observed == "e0c317edf030a2c132af8e380e62baec0092887d07c9d139209baa0c0e87e38d",
        ("unknown system linker inputs or default output", exe, observed),
    )
    return "historical GCC configure default executable", "a.out"


def inventory(path, arm):
    with path.open() as f:
        events = execs(f)
    sdk = {
        name: (SDK / file).stat()
        for name, file in [("rustc", "bin/rustc"), ("cargo", "bin/cargo"), ("wild", WILD)]
    }
    identities = {(s.st_dev, s.st_ino): n for n, s in sdk.items()}
    rustcs = []
    wild = []
    cargos = []
    others = []
    proxy = PROXIES / "rustup"
    proxy_id = (proxy.stat().st_dev, proxy.stat().st_ino)
    cargo_queries = []
    wild_queries = []
    for pid, exe, argv in events:
        file = Path(exe)
        s = file.stat() if file.is_file() else None
        role = identities.get((s.st_dev, s.st_ino)) if s else None
        if file.name == "rustc" and "--crate-name" in argv and role != "rustc":
            need(
                s is not None and (s.st_dev, s.st_ino) == proxy_id,
                ("unregistered rustc execution", pid, exe),
            )
        if (
            role == "rustc"
            and "--crate-name" in argv
            and not any(a.startswith("--print") for a in argv)
        ):
            crate = argv[argv.index("--crate-name") + 1]
            is_link = any(
                v in ("link-only", "ohm-link-only")
                or v.startswith("link-only=")
                or v.startswith("-Zlink-only")
                for v in argv
            )
            rustcs.append(
                dict(
                    pid=pid,
                    exe=exe,
                    crate=crate,
                    mode="link-only" if is_link else "full",
                    argv=argv,
                )
            )
            if crate in {"ruff", "ruff_python_ast", "ruff_python_parser"}:
                grade = any(v in ("ohm-branch-cache=yes", "-Zohm-branch-cache=yes") for v in argv)
                need(
                    grade == arm.endswith("on")
                    and any("ohm-check-relink-inputs" in v for v in argv),
                    ("default/explicit physical rustc flags", arm, crate),
                )
        elif role == "wild":
            if "-o" in argv:
                wild.append(dict(pid=pid, exe=exe, argv=argv, output=argv[argv.index("-o") + 1]))
            else:
                need(
                    set(argv[1:])
                    and set(argv[1:]) <= {"-v", "--version", "--help", "--print-output-format"},
                    ("unknown default-output Wild", argv[:10]),
                )
                wild_queries.append(dict(pid=pid, exe=exe, argv=argv))
        elif role == "cargo":
            bucket = cargo_queries if argv[1:] in (["--version"], ["-V"], ["-Vv"]) else cargos
            bucket.append(dict(pid=pid, exe=exe, argv=argv))
        elif file.name in ("ld", "ld.lld", "ld.bfd", "ld.gold", "wild", "rust-lld", "mold"):
            kind, output = other_link(exe, argv)
            others.append(dict(pid=pid, exe=exe, kind=kind, output=output, argv=argv))
    need(len(cargos) == 1, "expected exactly one physical Cargo")
    return dict(
        real_cargo=1,
        cargos=cargos,
        cargo_queries=cargo_queries,
        rustcs=rustcs,
        wild=len(wild),
        wild_processes=wild,
        wild_queries=wild_queries,
        other_linkers=others,
        successful_exec_count=len(events),
    )


def compact(source, target):
    with source.open("rb") as f, target.open("xb") as out, gzip.GzipFile(
        fileobj=out, mode="wb", mtime=0, compresslevel=2
    ) as buf:
        while data := f.read(2**20):
            buf.write(data)
    source.unlink()


def sessions(where, physical, work):
    from bindings import save, sha

    selected = {}
    for row in physical["rustcs"]:
        crate = row["crate"]
        if crate not in {"ruff", "ruff_python_ast", "ruff_python_parser"} or row["mode"] != "full":
            continue
        choices = [
            a.split("=", 1)[1]
            for a in row["argv"]
            if a.startswith(("incremental=", "-Cincremental="))
        ]
        need(len(choices) == 1, ("missing real incremental flag", crate, choices))
        base = Path(choices[0])
        need(
            base.is_relative_to(work / "target") or base.is_relative_to(work / "build"),
            ("foreign codegen cache", base),
        )
        artifact = []
        for owner in sorted(base.glob(crate + "-*")):
            for session in sorted(owner.glob("s-*")):
                if not session.is_dir() or session.name.endswith("-working"):
                    continue
                graph = session / "dep-graph.bin"
                products = session / "work-products.bin"
                if not (graph.is_file() and products.is_file()):
                    continue
                need(
                    graph.stat().st_size > 0 and products.stat().st_size > 0,
                    "empty compiler cache files",
                )
                artifact.append(
                    dict(
                        session=str(session.relative_to(work)),
                        graph_bytes=graph.stat().st_size,
                        work_products=[products.stat().st_size, sha(products)],
                        objects=sum(1 for _ in session.glob("*.o")),
                    )
                )
        need(artifact, ("missing actual owner incremental work products", crate, base))
        selected[str(row["pid"])] = dict(
            crate=crate, flag=str(base), current_or_prior_complete_sessions=artifact
        )
    save(where / "incremental-owners.json", selected)
