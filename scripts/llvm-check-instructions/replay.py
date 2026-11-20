import os
import json
import sys
import shutil
import hashlib
import subprocess
from pathlib import Path

root = Path.cwd()
src = root / "source"
reports = root / "receipts"
reports.mkdir()
sdk = root / "compiler"
target = root / "target"
shared = root / "shared"
trace = root / "llvm.log"
platform = "x86_64-unknown-linux-gnu"
ref = Path("lib/libLLVM.so.23.1-rust-dev")
old_llvm = "0324cb7d97454b4b0eb6317a61f015c9862a3d5a"
new_llvm = "bb335fde37c28311ce5db7203a2bfbb10db1853c"
fixed = os.environ["CANDIDATE"] == "44735982792"
versions = {
    "first": "ce0077c3e55ed6bd30e301729c8447af7cc6075a",
    "ASYNC401": "ff1770df69dfd6ff554a5623a11f790f8867e14f",
    "PLE0211": "4cec5d2d871ec065c593b24e0e49fc7d032f6061",
    "FURB103": "a3554f468ccfeef2511c4156774bc7d8d8c6c324",
}


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def save(path, contents):
    path.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n")


def install(key, llvm):
    path = root / key
    prefix = "ohm-1.100.0-3-" + platform
    (archive,) = path.rglob(prefix + ".tar.gz")
    (provenance,) = path.rglob(prefix + "-provenance.json")
    for item in [archive, provenance]:
        assert sha(item) == Path(str(item) + ".sha256").read_text().split()[0]
    proof = json.loads(provenance.read_bytes())
    assert proof["sources"]["llvm"]["revision"] == llvm and proof["target"] == platform
    if llvm == new_llvm:
        assert (
            proof["sources"]["rust"]["revision"]
            == "af392995e5ca93b70fc487b45dfdf6604dbbbc84"
        )
        assert (
            proof["coordinator"]["revision"]
            == "587a1d7554f18db1c8c52fe0cbfec0c1bf8fbd3f"
        )
    subprocess.run(
        ["tar", "xzf", archive, "--exclude=*/rust-docs", "--exclude=*/rust-src"],
        cwd=path,
        check=True,
    )
    bundle = path / ("rust-1.100.0-dev-" + platform)
    lib = bundle / "rustc" / ref
    if key == "fixed":
        subprocess.run(
            [
                "bash",
                bundle / "install.sh",
                "--disable-ldconfig",
                "--prefix=" + str(sdk),
                "--components=rustc,cargo,rust-std-" + platform,
            ],
            check=True,
        )
        assert sha(sdk / ref) == sha(lib)
    save(
        reports / (key + ".json"),
        dict(proof=proof, archive=sha(archive), llvm_library=sha(lib)),
    )
    return lib


def git(*args):
    return subprocess.check_output(["git", *args], cwd=src, text=True).strip()


def clear_linter():
    inc = target / "debug/incremental"
    paths = list(target.glob("debug/build/workspaces/*/*/ruff_linter"))
    paths.extend(shared.glob("debug/build/workspaces/*/*/ruff_linter"))
    assert len(paths) == 1, paths
    paths.extend(inc.glob("*/ruff_linter-*"))
    assert len(paths) > 1
    paths.extend(inc.glob("*/.ohm-checked-objects-v1"))
    for p in paths:
        assert p.resolve().is_relative_to(root)
        shutil.rmtree(p)
    assert not any(inc.rglob("llvmcache-*"))


def members(path):
    objects = {}
    with path.open("rb") as file:
        assert file.read(8) == b"!<arch>\n"
        names = b""
        while hdr := file.read(60):
            assert len(hdr) == 60
            name = hdr[:16].strip()
            size = int(hdr[48:58])
            block = file.read(size)
            file.read(size % 2)
            if name == b"//":
                names = block
            elif block.startswith(b"\x7fELF"):
                if name.startswith(b"/"):
                    name = names[int(name[1:]) :].split(b"/\n", 1)[0]
                if name.rstrip(b"/").endswith(b".o"):
                    assert name not in objects
                    objects[name] = hashlib.sha256(block).hexdigest()
    return objects


def cache():
    total = leaf = 0
    for p in (target / "debug/incremental").rglob("llvmcache-*"):
        if not p.is_file():
            continue
        n = p.stat().st_size
        total += n
        with p.open("rb") as f:
            if f.read(8) == b"OHMLEAF1":
                leaf += n
    return dict(total=total, leaf=leaf)


def exercise(stage, cli):
    if stage == "first":
        return []
    source = 'import pytest\n\nwith pytest.raises(ExceptionGroup):\n    raise ExceptionGroup("errors", [ValueError()])\n\nclass Example:\n    def method():\n        pass\n'
    rules = ["ASYNC401"]
    if stage != "ASYNC401":
        rules.append("PLE0211")
    p = subprocess.run(
        [
            cli,
            "check",
            "--isolated",
            "--no-cache",
            "--target-version",
            "py311",
            "--preview",
            "--output-format",
            "json",
            "--select",
            ",".join(rules),
            "-",
        ],
        input=source,
        text=True,
        capture_output=True,
        cwd=src,
    )
    rows = json.loads(p.stdout)
    assert p.returncode == 1 and [item["code"] for item in rows] == rules, rows
    return rows


def arm(role, library):
    for p in (target, shared):
        if p.exists():
            shutil.rmtree(p)
    (sdk / ref).unlink()
    shutil.copy2(library, sdk / ref)
    assert sha(sdk / ref) == sha(library)
    rustc = sdk / "bin/rustc"
    cargo = sdk / "bin/cargo"
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CARGO", "RUST", "OHM_"))
    }
    env.update(
        CARGO_BUILD_JOBS="6",
        RUSTC=str(rustc),
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_BUILD_DIR=str(shared),
        LLVM_OHM_DEBUG_OBJECT_CACHE_TRACE=str(trace),
        PATH=str(cargo.parent) + ":" + env["PATH"],
    )
    assert "CI" not in env
    log = reports / role
    log.mkdir()
    save(
        log / "driver.json",
        {
            p.name: sha(p)
            for p in [cargo, rustc, sdk / ref, *sdk.glob("lib/librustc_driver-*.so")]
        },
    )
    result = {}
    for stage in ["prime", "fresh", *versions]:
        rev = versions.get(stage, versions["first"])
        head = git("rev-parse", "HEAD")
        if head != rev:
            if stage != "prime":
                assert git("rev-parse", rev + "^") == head
            git("switch", "--detach", "--quiet", rev)
        assert git("rev-parse", "HEAD") == rev and not git("status", "--porcelain")
        if stage == "first":
            clear_linter()
        print(role, stage, rev, flush=True)
        count = log / (stage + ".tsv")
        cmd = [
            cargo,
            "build",
            "--locked",
            "-p",
            "ruff",
            "--bin",
            "ruff",
            "--message-format=json-render-diagnostics",
        ]
        if stage != "prime":
            cmd.append("--offline")
        if stage in versions:
            cmd = [root / "meter", rustc, count, *cmd]
        trace.unlink(missing_ok=True)
        p = subprocess.run(cmd, cwd=src, env=env, capture_output=True)
        if p.returncode:
            print(p.stderr.decode()[-5000:], file=sys.stderr)
            p.check_returncode()
        rows = [json.loads(line) for line in p.stdout.splitlines()]
        assert rows[-1] == dict(reason="build-finished", success=True)
        hashes = [
            v
            for row in rows
            if row["reason"] == "build-script-executed"
            for k, v in row.get("env", [])
            if k == "RUFF_COMMIT_HASH"
        ]
        assert hashes == [rev], hashes
        artifacts = [row for row in rows if row["reason"] == "compiler-artifact"]
        dirty = [v for v in artifacts if not v["fresh"]]
        if stage == "fresh":
            assert not dirty, dirty
        if stage not in versions:
            continue
        assert dirty and all(v["package_id"].startswith("path+") for v in dirty)
        objs = {}
        for item in artifacts:
            if item["package_id"].startswith("path+"):
                for fname in item["filenames"]:
                    if fname.endswith(".rlib"):
                        objs[Path(fname).name] = members(Path(fname))
        (lint,) = [v for k, v in objs.items() if k.startswith("libruff_linter-")]
        assert len(lint) == 256
        hits = 0
        if trace.exists():
            for line in trace.read_text().splitlines():
                _, cgu, event, *rest = line.split("\t")
                if event == "leaf-hit" and any(cgu.encode() in name for name in lint):
                    hits += 1
        if fixed and role == "candidate" and stage in ("ASYNC401", "PLE0211"):
            assert hits
        cli = target / "debug/ruff"
        graph = sorted(
            json.dumps(
                [r[k] for k in ["package_id", "target", "features", "profile"]],
                sort_keys=True,
            )
            for r in artifacts
        )
        shared_fields = dict(
            revision=rev,
            graph=digest(graph),
            dirty=sorted(v["target"]["name"] for v in dirty),
            objects=sum(map(len, objs.values())),
            object_hashes=digest({k: sorted(v.values()) for k, v in objs.items()}),
            linter_objects=len(lint),
            cli=sha(cli),
            diagnostics=exercise(stage, cli),
        )
        total, enabled, running = map(
            int, Path(str(count) + ".tree").read_text().split()
        )
        (linter,) = [
            int(row.split()[3])
            for row in count.read_text().splitlines()
            if row.split()[1] == "ruff_linter"
        ]
        result[stage] = dict(
            common=shared_fields,
            instructions=total,
            linter=linter,
            enabled=enabled,
            running=running,
            hits=hits,
            cache=cache(),
        )
        save(log / "results.json", result)
    return result


providers = {
    "reference": install("control", old_llvm),
    "candidate": install("fixed", new_llvm if fixed else old_llvm),
}
order = list(providers)
if int(os.environ["PAIR"]) % 2 == 0:
    order.reverse()
state = {role: arm(role, providers[role]) for role in order}
changes = {}
for stage in versions:
    before = state["reference"][stage]
    after = state["candidate"][stage]
    assert before["common"] == after["common"], [
        (k, v, after["common"][k])
        for k, v in before["common"].items()
        if v != after["common"][k]
    ]
    changes[stage] = 100 * (after["instructions"] / before["instructions"] - 1)
print(changes)
save(
    reports / "comparison.json",
    dict(order=order, changes=changes, pair=os.environ["PAIR"]),
)
