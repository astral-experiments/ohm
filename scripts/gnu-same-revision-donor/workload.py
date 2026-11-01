"""Ordinary no-quarantine Ruff return exercises the exact E and rebuilt direct child on one host."""

from pathlib import Path
import argparse
import gzip
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [
    str(HERE),
    str(HERE.parent / "branch-return-pmu"),
    str(HERE.parent / "ohm-packed-ruff"),
]
import binding as reg
import bindings as b
import study as kit
import events
import donors
import donor_open
import live_driver
import native_outputs as out

OWN = donors.OWN
A, B = kit.REVS["A"], kit.REVS["B"]
Y, X = "ast-B", "ast-A"
CLI = [
    "cargo",
    "+ohm",
    "build",
    "--locked",
    "--offline",
    "-j2",
    "-p",
    "ruff_python_edits",
    "--lib",
    "--message-format=json",
]
NODES = "crates/ruff_python_ast/src/nodes.rs"
LIB = "crates/ruff_python_ast/src/lib.rs"
SOURCE_LIB = "712c897ad642964bb8526dcb13d97bb1917add11cb627e894b738c6f4affa428"
EDITED_LIB = "cb988a3c7709f0a5cb184ceb5776f67f527f0c458d8b5111f9595d448f12f06b"
SOURCE_NODE = "299c122da4caf5214b15cb4d36dba18ca7855beb31ea50f9050d9a0cc816275c"
EDITED_NODE = "dbda1ba0b8c4a8ae98c62da763c9128260db17fc0c3911e2a377073a5284e937"
INVALID = b'\nconst _AST_REAL_DONOR_ERROR: u8 = "wrong";\n'
REF = "/__ENROLLED_RUFF__"
HIST = ("Y-B", "X-A", "X-B", "return", "repeat", "invalid", "repair", "semantic")
GRAPH = json.loads((HERE / "inputs/graph.json").read_bytes())
KERNEL = "19f9a67b032cce44cea1e3bb7e324558cd9abd0a"
ROLE_SET = {"Eon", "Don"}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def source_state():
    return {
        "branch": kit.git("symbolic-ref", "--short", "HEAD"),
        "head": kit.git("rev-parse", "HEAD"),
        "tree": kit.git("rev-parse", "HEAD^{tree}"),
        "X": kit.git("rev-parse", X),
        "Y": kit.git("rev-parse", Y),
        "dirty": kit.git("status", "--porcelain"),
        "nodes": reg.sha(kit.TREE / NODES),
        "lib": reg.sha(kit.TREE / LIB),
        "edits": kit.git("rev-parse", "HEAD:crates/ruff_python_edits"),
    }


def replace(file, old, new, before, after):
    path = kit.TREE / file
    body = path.read_bytes()
    reg.need(reg.digest(body) == before and body.count(old) == 1, "incorrect edit base: " + file)
    path.write_bytes(body.replace(old, new))
    reg.need(reg.sha(path) == after, "unexpected changed source")


def comment():
    replace(
        NODES,
        b"// introducing it would emit a dead code warning",
        b"// introducing it would emit a dead-code warning",
        SOURCE_NODE,
        EDITED_NODE,
    )


def semantic():
    replace(LIB, b'"pyi" => Self::Stub,', b'"pyi" => Self::Python,', SOURCE_LIB, EDITED_LIB)


def init_refs():
    kit.git("switch", "--detach", "--quiet", B)
    for name, rev in ((Y, B), (X, A)):
        kit.git("branch", "-f", name, rev)
    kit.git("switch", "--quiet", Y)
    reg.need(
        not kit.git("status", "--porcelain"), "dirty beginning of new independently empty history"
    )


def smoke(observer):
    obs_src = observer / "scripts/branch-return-execstop"
    reg.need(reg.rev(observer, "HEAD") == KERNEL, "foreign observer source")
    k = obs_src / "kernel/read_events.py"
    reg.need(
        reg.sha(k) == "99ce628b4cd2e422857f9b4ac9dd59b135cd6c306848b09b0cbdfe7a6d856b41",
        "foreign v3 parser",
    )
    return module("same_revision_schema_3", k)


def boot_receipts(observer):
    rd = smoke(observer)
    od = observer / "scripts/branch-return-execstop"
    base = b.OUT / "donor-fixtures"
    base.mkdir()
    group = od / "group_fixtures.py"
    subprocess.run(
        [
            sys.executable,
            "-IB",
            group,
            "run",
            b.ROOT / "donor-observer",
            base / "group",
            b.PARK / "E" / b.WILD,
        ],
        check=True,
    )
    rec = subprocess.check_output([sys.executable, "-IB", group, "reopen", base / "group"])
    reg.need(
        rec == (base / "group/group-v2/qualified.json").read_bytes()
        and json.loads(rec)["schema"] == 3,
        "actual host failed authenticated v3 observer validation",
    )
    binary = b.ROOT / "event-only-cold"
    subprocess.run(
        [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            HERE / "exec_events.c",
            "-lcrypto",
            "-o",
            binary,
        ],
        check=True,
    )
    for tag, cmd, code, n in (
        ("true", ["/usr/bin/true"], 0, 1),
        ("duplicate", [b.ROOT / "donor-observer/fixture", "duplicate"], 19, 3),
        ("thread", [b.ROOT / "donor-observer/fixture", "thread"], 37, 2),
    ):
        f = base / (tag + ".tsv")
        test = subprocess.run([binary, f, "--", *cmd], capture_output=True)
        body = f.read_bytes()
        reg.need(
            test.returncode == code and len(events.reopen(body, code)["execs"]) == n,
            "cold event control",
        )
        try:
            events.reopen(body[: body.rindex(b"OK\t")], code)
        except ValueError:
            pass
        else:
            raise ValueError("truncated cold kernel ledger accepted")
    write = out.write
    write(
        base / "toolchain.json",
        dict(
            event_only=reg.sha(binary),
            v3=reg.sha(b.ROOT / "donor-observer/observe"),
            observer_source=KERNEL,
            fixtures=reg.digest(rec),
        ),
    )
    return rd


def project(ledger, expected, env, sdk, rd, cold):
    parsed = (
        events.reopen(ledger, expected)
        if cold
        else rd.parse(ledger, expected_code=expected, expected_schema=3)
    )
    decoded = parsed["execs"]
    ids = {}
    for role, name in (("cargo", "bin/cargo"), ("rustc", "bin/rustc"), ("wild", b.WILD)):
        p = sdk / name
        s = p.stat()
        ids[role] = (s.st_dev, s.st_ino, reg.sha(p))
    cargo = []
    comp = []
    wild = []
    for row in decoded:
        img = row["image"]
        key = (img["dev"], img["ino"], img["sha256"])
        argv = row["argv"]
        if key == ids["cargo"]:
            cargo.append(row)
        if key == ids["wild"]:
            wild.append(row)
        if "--crate-name" in argv and key == ids["rustc"]:
            name = argv[argv.index("--crate-name") + 1]
            mode = (
                "probe"
                if name == "___" or any(x.startswith("--print=") or x == "--print" for x in argv)
                else (
                    "link-only"
                    if any(x.endswith(".rlink") or x.startswith("-Zlink-only") for x in argv)
                    else "compile"
                )
            )
            if name in OWN and mode == "compile":
                reg.need(
                    argv.count("-Zohm-branch-cache=yes") == 1
                    and any(x.startswith("incremental=") for x in argv),
                    "not authentic enabled workspace rustc",
                )
            comp.append(dict(pid=row["pid"], argv=argv, name=name, mode=mode, image=img))
    reg.need(
        len(cargo) == 1
        and cargo[0]["argv"][1:] == CLI[2:]
        and env["CARGO_BUILD_BUILD_DIR"] == str(b.WORK / "build")
        and env["CARGO_TARGET_DIR"] == str(b.WORK / "target"),
        "foreign installed Cargo, argv, or workspace layout",
    )
    return cargo[0], comp, wild


def visit(root, tag, role, env, rd, expected, flavor="Stub", registered=None):
    where = root / tag
    where.mkdir()
    source = source_state()
    expected_rc = 101 if tag == "invalid" else 0
    reg.need(
        source["head"] == expected
        and source["edits"] == "c990f5b12d6c68b4565af06e8d40e7c83e066c89",
        "wrong Ruff revision",
    )
    out.write(where / "source.json", source)
    if registered:
        out.write(where / "registered-donors.json", registered)
    cold = tag == "Y-B" or tag.startswith("empty-")
    binary = b.ROOT / ("event-only-cold" if cold else "donor-observer/observe")
    ledger = b.WORK / "donor-observed.tsv"
    ledger.unlink(missing_ok=True)

    def cargo(folder, rc):
        paths = [
            Path(f["path"])
            for owner in (registered or {}).values()
            for side in ("X", "Y")
            for f in owner[side]["tables"].values()
        ]
        w = donor_open.Watch(paths) if registered else None
        try:
            c = out.run([binary, ledger, "--", *CLI], env, kit.TREE, folder, "cargo", rc)
        finally:
            if w:
                out.write(folder / "kernel-file-opens.json", w.close())
            if ledger.is_file():
                out.write(folder / "kernel.tsv.gz", ledger.read_bytes())
        data = ledger.read_bytes()
        im, comp, wild = project(data, rc, env, b.SDK, rd, cold)
        out.write(folder / "images.json.gz", {"cargo": im, "comp": comp, "wild": wild})
        rows = list(map(json.loads, c.stdout.splitlines()))
        reg.need(
            rows[-1] == {"reason": "build-finished", "success": rc == 0}, "wrong Cargo terminal"
        )
        return rows, wild, comp

    driver = json.loads((b.OUT / "sdk" / (role + ".json")).read_bytes())["driver"]
    rows, wild, comp = live_driver.watch(
        cargo, where, expected_rc, b.SDK, b.SDK / driver, out.write, None
    )
    full = [x for x in comp if x["mode"] == "compile"]
    typed = [r for r in rows if r["reason"] == "compiler-artifact"]
    d = [
        r["message"]
        for r in rows
        if r["reason"] == "compiler-message" and r["message"]["level"] == "error"
    ]
    info = dict(
        source=source,
        full=full,
        native_links=wild,
        typed=len(typed),
        code=expected_rc,
        allocation=donors.allocated(b.WORK / "target", b.WORK / "build"),
    )
    if registered:
        obs = json.loads((where / "kernel-file-opens.json").read_bytes())
        info["used_donors"] = donors.verify_opens(registered, obs, full, role)
    if expected_rc:
        reg.need(
            len(d) == 1
            and d[0].get("code", {}).get("code") == "E0308"
            and any(
                span["is_primary"]
                and span["file_name"].endswith(LIB)
                and any("_AST_REAL_DONOR_ERROR" in l["text"] for l in span["text"])
                for span in d[0]["spans"]
            )
            and [r["name"] for r in full] == [OWN[0]],
            "wrong real Ruff rejection",
        )
    else:
        reg.need(not d, "unexpected positive compilation error")
        info.update(
            out.client(
                env,
                kit.TREE,
                b.WORK,
                where,
                b.OUT / "ordinary-ruff/bodies",
                typed,
                64 if expected == A else 56,
                flavor,
                HERE / "inputs/client.rs",
            )
        )
        scripts = sorted(
            r["package_id"].replace(str(kit.TREE), REF)
            for r in rows
            if r["reason"] == "build-script-executed"
        )
        reg.need(
            info["graph"] == GRAPH["typed"] and scripts == GRAPH["scripts"],
            "wrong complete 42-unit source graph",
        )
        info["scripts"] = scripts
    info["sessions"] = donors.snapshot(b.WORK / "target", role)
    info["unfinished_directories"] = donors.working(b.WORK / "target")
    out.write(where / "result.json.gz", info)
    return info


def fresh():
    kit.git("restore", "--", NODES, LIB)
    init_refs()
    b.fresh_outputs()


def history(folder, role, rd, env, dirty):
    fresh()
    folder.mkdir()

    def v(tag, ref=B, flavor="Stub", register=None):
        return visit(folder, tag, role, env, rd, ref, flavor, register)

    r = {}
    r["Y-B"] = v("Y-B")
    kit.git("switch", "--quiet", X)
    r["X-A"] = v("X-A", A)
    kit.git("merge", "--ff-only", "--quiet", Y)
    if dirty:
        semantic()
    r["X-B"] = v("X-B", flavor="Python" if dirty else "Stub")
    reg.need(bool(r["X-B"]["source"]["dirty"]) == dirty, "incorrect semantic donor cleanliness")
    if dirty:
        kit.git("restore", "--", LIB)
    kit.git("switch", "--quiet", Y)
    reg.need(not source_state()["dirty"], "unrelated changes crossed true switch")
    comment()
    register = donors.enrollment(r["Y-B"], r["X-A"], r["X-B"], role, B)
    reg.need(
        donors.snapshot(b.WORK / "target", role) == r["X-B"]["sessions"],
        "donors changed between branches",
    )
    r["return"] = v("return", register=register)
    r["repeat"] = v("repeat")
    original = (kit.TREE / LIB).read_bytes()
    reg.need(reg.digest(original) == SOURCE_LIB, "invalid-edit source base")
    (kit.TREE / LIB).write_bytes(original + INVALID)
    r["invalid"] = v("invalid")
    (kit.TREE / LIB).write_bytes(original)
    r["repair"] = v("repair")
    semantic()
    r["semantic"] = v("semantic", flavor="Python")
    return r


def compare(v, clean):
    reg.need(
        v["native"] == clean["native"]
        and v["elf"] == clean["elf"]
        and all(v["products"][o]["cgus"] == clean["products"][o]["cgus"] for o in OWN),
        "warm/empty changed native CGUs, complete executable, or behavior",
    )


def acquire_roles():
    reg.job()
    b.SDK.parent.mkdir(parents=True, exist_ok=True)
    b.PROXIES.mkdir(parents=True, exist_ok=True)
    settings = b.HOME / ".rustup/settings.toml"
    if not settings.exists():
        settings.write_text('version = "12"\nprofile = "minimal"\n')
    rustup = Path(shutil.which("rustup")).resolve(strict=True)
    for name in ("rustup", "cargo", "rustc", "rustdoc"):
        dest = b.PROXIES / name
        if not dest.exists():
            shutil.copy2(rustup, dest)
        reg.need(reg.sha(dest) == reg.sha(rustup), "foreign launcher")
    return {
        r: json.loads((b.OUT / "sdk" / (r + ".json")).read_bytes())["files"] for r in ("E", "D")
    }


def activate(role, rows):
    where = b.OUT / ("subject-" + role)
    where.mkdir()
    return b.activate(
        role + "on", rows, where, permitted=ROLE_SET, source_manifest=reg.SOURCE_RECEIPT
    )


def main(observer):
    reg.job()
    records = acquire_roles()
    rd = boot_receipts(observer)
    result = b.OUT / "ordinary-ruff"
    result.mkdir()
    (result / "bodies").mkdir()
    env = activate("E", records)
    (b.HOME / ".cargo/config.toml").write_text(
        "[build]\nbuild-dir = " + json.dumps(str(b.WORK / "build")) + "\n"
    )
    b.prepare_inputs(kit, env)
    from native_provider import exercise

    for role in ("E", "D"):
        if role == "D":
            env = activate("D", records)
        folder = result / role
        folder.mkdir()
        exercise(b, env, role, folder / "provider", rd)
        sets = {d: history(folder / d, role, rd, env, d == "dirty") for d in ("clean", "dirty")}
        refs = {}
        for state in ("comment", "semantic"):
            fresh()
            comment()
            if state == "semantic":
                semantic()
            refs[state] = visit(
                folder,
                "empty-" + state,
                role,
                env,
                rd,
                B,
                "Python" if state == "semantic" else "Stub",
            )
        claims = {}
        for name, hist in sets.items():
            for stage in ("return", "repeat", "repair"):
                compare(hist[stage], refs["comment"])
            compare(hist["semantic"], refs["semantic"])
            count = [x["name"] for x in hist["return"]["full"]]
            want = list(OWN) if role == "E" or name == "dirty" else [OWN[0]]
            # A good dirty donor has actually different source, so its normal recovery is separately observed.
            reg.need(
                count == want
                and not hist["repeat"]["full"]
                and all(not hist[p]["native_links"] for p in ("return", "repeat")),
                ("structural result refused", role, name, count),
            )
            claims[name] = {
                "return": count,
                "repeat": [],
                "opens": hist["return"]["used_donors"],
                "elf": hist["return"]["elf"],
                "allocation": hist["return"]["allocation"],
            }
        reg.need(
            refs["comment"]["elf"] != refs["semantic"]["elf"],
            "real body change was not discriminating",
        )
        out.write(
            folder / "qualified.json",
            {"claims": claims, "refs": {k: v["elf"] for k, v in refs.items()}},
        )
    out.write(
        result / "qualified.json",
        {
            "qualified": True,
            "source": [reg.OLD, reg.NEW],
            "cargo": b.CARGO,
            "observer": KERNEL,
            "roles": {r: reg.sha(result / r / "qualified.json") for r in records},
            "command": CLI,
            "scope": "No-quarantine, local developer Cargo. Structural and native qualification only.",
        },
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
