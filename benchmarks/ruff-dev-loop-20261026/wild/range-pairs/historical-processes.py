"""Verify one root Cargo and the complete historical rustc, Clang and Wild process tree."""

import collections, hashlib, os, re, shutil
from pathlib import Path


def fingerprint(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def native_roster(directory, expected_cargo, rustc, clang, wild):
    found = collections.defaultdict(list)
    pending = {}
    bootstrap = {
        Path(shutil.which("cargo")).resolve(),
        (wild.parent / "clang").resolve(),
    }
    for line in (directory / "execs").read_text().splitlines():
        start = re.match(r"^\s*(\d+)\s+execve\(.*<unfinished \.\.\.>$", line)
        if start:
            pid = start[1]
            assert pid not in pending
            pending[pid] = line[: line.rindex("<unfinished ...>")].rstrip()
            continue
        end = re.match(r"^\s*(\d+)\s+<\.\.\. execve resumed>(.*)$", line)
        if end:
            line = pending.pop(end[1]) + end[2]
        m = re.match(r'^\s*(\d+)\s+execve\("([^"]+)".*\)\s+=\s+0$', line)
        if not m:
            continue
        f = Path(m[2]).resolve()
        for label, p in [
            ("cargo", expected_cargo),
            ("rustc", rustc),
            ("clang", clang),
            ("wild", wild),
        ]:
            if f != p.resolve():
                continue
            name = None
            if label == "rustc":
                name = re.search(r'"--crate-name", "([^"]+)"', line)[1]
            found[label].append((int(m[1]), name))
            break
        else:
            assert (
                f in bootstrap
                or f.name == "rustc-wrapper"
                and f.parent.name
                in ["historical-collectors-build", "historical-collectors-test"]
            ), f
    assert not pending, pending
    assert (
        len(found["cargo"]) == 1
        and len(found["clang"]) == len(found["wild"])
        and len(found["rustc"]) >= len(found["wild"]) > 0
    )
    return dict(found)


def observations(directory, ref, cargo, rustc, clang, wild, driver, observed):
    (cargo_pidfile,) = directory.glob("cargo.*.ir")
    pid = cargo_pidfile.name.split(".")[1]
    a = [x.split() for x in cargo_pidfile.read_text().splitlines()]
    assert (
        a[0] == ["B", pid, "0", "0"]
        and a[-1] == ["P", pid, "0", "0"]
        and all(len(x) == 4 and x[0] in "BTFS P" and x[1] == pid for x in a)
    )
    T = sorted(x[2] for x in a if x[0] == "T")
    F = sorted(x[2] for x in a if x[0] == "F")
    assert len(T) == len(set(T)) and T == F
    (cargo_arg,) = directory.glob("cargo.*.argv")
    assert (
        cargo_arg.name.split(".")[1] == pid
        and Path(os.fsdecode(cargo_arg.read_bytes().split(b"\0")[0])).resolve()
        == cargo.resolve()
    )
    assert set(Path(z).resolve() for z in observed.get("cargo", ())) == {
        cargo.resolve()
    }
    items = [
        dict(
            role="cargo",
            pid=int(pid),
            ir=sum(int(x[3]) for x in a if x[0] == "F"),
            raw=fingerprint(cargo_pidfile),
            image=str(cargo.resolve()),
            threads=len(T),
        )
    ]
    expected = {
        str(p.resolve()): role
        for p, role in [(rustc, "rustc"), (clang, "clang"), (wild, "wild")]
    }
    args = {int(p.name.split(".")[1]): p for p in directory.glob("rustc.*.argv")}
    assert len(args) == len(ref["rustc"])
    for guest in sorted(directory.glob("guest.*")):
        pid = int(guest.suffix[1:])
        vg = directory / f"vg.{pid}"
        log = vg.read_text()
        assert log.count(" I refs:") == 1 and "Process terminating" not in log
        with guest.open() as fd:
            for line in fd:
                if line.startswith("cmd: "):
                    cmd = line[5:].split()
                if line.startswith("summary: "):
                    ir = int(line.split()[1])
                    break
            else:
                raise ValueError(("missing counter", guest))
        real = str(Path(cmd[0]).resolve())
        role = expected[real]
        record = dict(
            role=role,
            pid=pid,
            ir=ir,
            image=real,
            raw=fingerprint(guest),
            log_sha256=fingerprint(vg),
        )
        assert ir > 0
        reported = int(re.search(r" I refs:\s*([\d,]+)", log)[1].replace(",", ""))
        assert reported == ir
        if role == "rustc":
            argv = args[pid].read_bytes().split(b"\0")
            name = os.fsdecode(argv[argv.index(b"--crate-name") + 1])
            assert name == cmd[cmd.index("--crate-name") + 1]
            loaded = {
                Path(x.split("Reading syms from ", 1)[1].strip()).resolve()
                for x in log.splitlines()
                if "Reading syms from " in x and x.rstrip().endswith("/" + driver.name)
            }
            assert loaded == {driver.resolve()}
            record.update(
                crate=name,
                driver=str(driver.resolve()),
                command_sha256=fingerprint(args[pid]),
            )
        elif role == "clang":
            assert "-Wl,--no-fork" in cmd
        else:
            assert "--no-fork" in cmd or len(cmd) == 2 and cmd[1].startswith("@")
        items.append(record)
    assert (
        len(list(directory.glob("vg.*"))) + 1
        == len(items)
        == len({x["pid"] for x in items})
    )
    assert collections.Counter(x["role"] for x in items) == {
        key: len(val) for key, val in ref.items()
    }
    assert sorted(x["crate"] for x in items if x["role"] == "rustc") == sorted(
        name for _, name in ref["rustc"]
    )
    counts = {k: sum(x["ir"] for x in items if x["role"] == k) for k in ref}
    return {"processes": items, "counts": counts, "total": sum(counts.values())}
