"""Reopen the complete original native/source receipts on GNU without relying on live SDK inodes."""

import argparse
import gzip
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNNER_TEMP", tempfile.gettempdir())
import workload as w
import donors
import driver_map
import events
import native_provider
from binding import need, digest, sha, OLD, NEW, SOURCE_RECEIPT
from native_outputs import negative, archive

A_NODE = "19d7a907a8ff1cb9a6030e04d20d4e58e78a03a9de7d40c67f5644ad45ab025c"
A_LIB = w.SOURCE_LIB
INVALID_LIB = "3a94a42fbb534f67bb71b073f678cb71e59ae1267ad8b7a4de91713f98126192"


def body(path):
    raw = path.read_bytes()
    return gzip.decompress(raw) if path.suffix == ".gz" else raw


def load(path):
    return json.loads(body(path))


def command(folder, tag, code):
    record = load(folder / (tag + ".json"))
    stdout = body(folder / (tag + ".stdout.gz"))
    stderr = body(folder / (tag + ".stderr.gz"))
    need(
        record["code"] == code
        and record["stdout"] == digest(stdout)
        and record["stderr"] == digest(stderr),
        "exit or original output mismatch in " + str(folder / tag),
    )
    return record, stdout, stderr


def file_id(row):
    return (row["dev"], row["ino"], row["sha256"])


def trace(raw, rd, cold, code):
    return (
        events.reopen(raw, code)["execs"]
        if cold
        else rd.parse(raw, expected_code=code, expected_schema=3)["execs"]
    )


def role_images(execs, record, command):
    ids = {k: (v[1], v[2], v[0]) for k, v in record["files"].items()}
    cargo = [i for i in execs if file_id(i["image"]) == ids["bin/cargo"]]
    need(len(cargo) == 1 and cargo[0]["argv"][1:] == command[2:], "actual installed Cargo/argv")
    comp = []
    wild = []
    for row in execs:
        ident = file_id(row["image"])
        argv = row["argv"]
        if ident == ids[w.b.WILD]:
            wild.append(row)
        if "--crate-name" not in argv:
            continue
        if ident != ids["bin/rustc"]:
            need(Path(row["exe"]).name != "rustc", "another installed compiler produced a unit")
            continue
        name = argv[argv.index("--crate-name") + 1]
        probe = name == "___" or any(x == "--print" or x.startswith("--print=") for x in argv)
        link = any(x.startswith("-Zlink-only") or x.endswith(".rlink") for x in argv)
        mode = "probe" if probe else ("link-only" if link else "compile")
        if name in w.OWN and mode == "compile":
            need(
                argv.count("-Zohm-branch-cache=yes") == 1
                and sum(x.startswith("incremental=") for x in argv) == 1,
                "workspace rustc lacks ordinary incremental/retention flags",
            )
        comp.append(dict(pid=row["pid"], name=name, mode=mode, argv=argv, image=row["image"]))
    return {"cargo": cargo[0], "comp": comp, "wild": wild}


def cargo(folder, code, cli, cold, record, rd, provider=False):
    cmd, stdout, stderr = command(folder, "cargo", code)
    argv = cmd["argv"]
    need(
        len(argv) == len(cli) + 3
        and argv[2] == "--"
        and argv[3:] == cli
        and Path(argv[0]).name == ("event-only-cold" if cold else "observe"),
        "instrument or literal command",
    )
    raw = body(folder / ("kernel.tsv" if provider else "kernel.tsv.gz"))
    execs = trace(raw, rd, cold, code)
    images = role_images(execs, record, cli)
    rows = [json.loads(line) for line in stdout.splitlines()]
    need(
        rows
        and rows[-1] == {"reason": "build-finished", "success": code == 0}
        and images["cargo"]["cwd"] == cmd["cwd"],
        "raw Cargo terminal/cwd disagrees",
    )
    return rows, images, execs, raw, stdout, stderr


def original(cas, row):
    size, key = row
    need(
        isinstance(size, int) and 0 < size < 64 * 2**20 and re.fullmatch(r"[0-9a-f]{64}", key),
        "bad native body identity",
    )
    data = body(cas / (key + ".gz"))
    need(len(data) == size and digest(data) == key, "incorrect native original body")
    return data


def execute(cas, row, args, stdout, tmp, already):
    key = (tuple(row), tuple(args), stdout)
    if key in already:
        return
    data = original(cas, row)
    need(
        data[:6] == b"\x7fELF\x02\x01"
        and struct.unpack_from("<HH", data, 16) in ((2, 62), (3, 62)),
        "not a complete GNU x86-64 executable",
    )
    path = tmp / row[1]
    if not path.exists():
        path.write_bytes(data)
        path.chmod(0o500)
    result = subprocess.run(
        [path, *args],
        cwd=tmp,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=15,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    need(
        result.returncode == 0 and result.stdout == stdout and not result.stderr,
        "native replay differed",
    )
    already.add(key)


def source(info, tag, dirty):
    s = info["source"]
    a = tag == "X-A"
    early = tag in ("Y-B", "X-A", "X-B")
    semantic = tag in ("semantic", "empty-semantic") or (tag == "X-B" and dirty)
    need(
        s["head"] == (w.A if a else w.B)
        and s["tree"] == w.kit.TREES["A" if a else "B"]
        and s["branch"] == (w.X if tag in ("X-A", "X-B") else w.Y)
        and s["Y"] == w.B
        and s["X"] == (w.A if tag in ("Y-B", "X-A", "empty-comment", "empty-semantic") else w.B)
        and s["edits"] == "c990f5b12d6c68b4565af06e8d40e7c83e066c89",
        "foreign Ruff history",
    )
    node = w.SOURCE_NODE if early else w.EDITED_NODE
    lib = w.EDITED_LIB if semantic else w.SOURCE_LIB
    # Historical A has different source in these two files. Its complete authentic Git IDs are fixed separately.
    if a:
        node, lib = A_NODE, A_LIB
    if tag == "invalid":
        lib = INVALID_LIB
    paths = sorted(([] if early else [w.NODES]) + ([w.LIB] if semantic or tag == "invalid" else []))
    need(
        s["nodes"] == node
        and s["lib"] == lib
        and sorted(x.strip().removeprefix("M ") for x in s["dirty"].splitlines()) == paths,
        "different tracked Ruff body, comment or worktree edits",
    )
    return 64 if a else 56, "Python" if semantic else "Stub"


def live(folder, full, record, sdk):
    drivers = load(folder / "live-drivers.json.gz")
    d = record["files"][record["driver"]]
    path = sdk / record["driver"]
    proof = drivers["reference"]
    driver_map.check_reference(proof, path, d)
    need(not drivers["refused"], "live compiler sampler refused")
    for c in full:
        if c["name"] not in w.OWN:
            continue
        pid = c["pid"]
        v = drivers["actual"][str(pid)]
        need(
            (v["dev"], v["ino"]) == (d[1], d[2])
            and v["pid"] == pid
            and v["argv"][1:] == c["argv"][1:]
            and v["ancestry"][0] == drivers["worker_pid"]
            and v["maps"],
            "selected compiler has no genuine mapped driver",
        )
        driver_map.check_process(proof, path, d, v["mount_namespace"], v["visible"], v["maps"])


def external_args(rows):
    selected = {}
    for name in (*w.OWN, "ruff_text_size"):
        (artifact,) = [r for r in rows if r["target"]["name"] == name]
        (provider,) = [f for f in artifact["filenames"] if f.endswith(".rlib")]
        selected[name] = provider
    search = {
        Path(p).parent
        for r in rows
        for p in r["filenames"]
        if Path(p).suffix in (".rlib", ".so", ".rmeta")
    }
    right = ["rustc", "+ohm", "--edition=2024", "--crate-name", "ast_consumer_verify"]
    for k, p in sorted(selected.items()):
        right += ["--extern", k + "=" + p]
    for p in sorted(search):
        right += ["-L", "dependency=" + str(p)]
    return selected, right


def check_client(folder, cas, info, raw, imgs, width, flavor, tmp, execs, checked):
    tree = imgs["cargo"]["cwd"]
    rows = [x for x in raw if x["reason"] == "compiler-artifact"]
    names = sorted(
        (
            [
                r["package_id"].replace(tree, w.REF),
                r["target"]["name"],
                r["target"]["kind"],
                r["target"]["crate_types"],
                r["features"],
                r["profile"],
            ]
            for r in rows
        ),
        key=lambda x: json.dumps(x, sort_keys=True),
    )
    scripts = sorted(
        r["package_id"].replace(tree, w.REF) for r in raw if r["reason"] == "build-script-executed"
    )
    need(
        len(rows) == 37
        and names == w.GRAPH["typed"] == info["graph"]
        and scripts == w.GRAPH["scripts"] == info["scripts"]
        and all(r["filenames"] for r in rows),
        "wrong Cargo graph",
    )
    selected, right = external_args(rows)
    need(
        selected == info["provider_paths"] and set(info["products"]) == set(w.OWN),
        "actual typed provider mismatch",
    )
    origin = Path(tree).parent
    src = str(origin / "work/returned-native-client.rs")
    output = str(origin / "work/returned-native-client")
    client_source = (HERE / "inputs/client.rs").read_bytes()
    need(
        (folder / "client-input.rs").read_bytes() == client_source
        and (folder / "wrong-input.rs").read_bytes()
        == client_source
        + f"\nconst _: [(); {120-width}] = [(); std::mem::size_of::<Expr>()];\n".encode(),
        "incorrect actual consumer source",
    )
    good, stdout, stderr = command(folder, "client", 0)
    need(
        good["argv"] == right + ["-o", output, src]
        and good["cwd"] == tree
        and not stderr
        and not stdout,
        "substituted actual Rust client or extern files",
    )
    bad, _, stderr = command(folder, "wrong", 1)
    need(
        bad["argv"]
        == right
        + [
            "--emit=metadata",
            "--error-format=json",
            "-o",
            str(origin / "work/returned-wrong.rmeta"),
            src,
        ]
        and negative(stderr, Path(src)),
        "missing actual typed opposite-size error",
    )
    for name, values in info["products"].items():
        cmd, stdout, stderr = command(folder, "listing-" + name, 0)
        need(
            cmd["argv"] == ["rustc", "+ohm", "-Zls=root", selected[name]]
            and not stderr
            and re.findall(rb"^public_hash ([0-9a-f]{32})$", stdout, re.M)
            == [values["public"].encode()],
            "selected rlib metadata identity",
        )
        raw_archive = original(cas, values["rlib"])
        contents = archive(
            raw_archive, name, lambda data: [len(data), digest(data)], values["rlib"]
        )
        need(
            contents == {k: v for k, v in values.items() if k != "public"},
            "physical rlib disagrees with member hashes",
        )
        need(
            len(values["cgus"])
            == (3 if name == w.OWN[1] else (94 if width == 56 else len(values["cgus"])))
            and values["cgus"]
            and "lib.rmeta" in values["non_native"],
            "missing CGU or metadata",
        )
        for member, row in values["cgus"].items():
            key = tuple(row)
            need(
                re.fullmatch(re.escape(name) + r"-[a-f0-9]+\.[0-9a-z]+", member), "foreign CGU name"
            )
            if key not in checked:
                data = original(cas, row)
                need(
                    data[:6] == b"\x7fELF\x02\x01"
                    and struct.unpack_from("<HH", data, 16) == (1, 62),
                    "not the complete CGU",
                )
                checked.add(key)
    for ext, expected in (("pyi", flavor), ("py", "Python")):
        cmd, stdout, stderr = command(folder, "run-" + ext, 0)
        value = f"{width} x {expected}\n"
        need(
            cmd["argv"] == [output, ext]
            and not stderr
            and stdout == value.encode()
            and info["native"][ext] == value,
            "unexpected original native verdict",
        )
        execute(cas, info["elf"], [ext], stdout, tmp, execs)


def visit(folder, role, rd, record, cas, tmp, execs, checked, dirty):
    info = load(folder / "result.json.gz")
    tag = folder.name
    need(
        info["source"] == load(folder / "source.json"),
        "source projection differs from recorded worktree",
    )
    width, flavor = source(info, tag, dirty)
    code = 101 if tag == "invalid" else 0
    typed, imgs, _, _, _, _ = cargo(
        folder, code, w.CLI, tag == "Y-B" or tag.startswith("empty-"), record, rd
    )
    allfull = [c for c in imgs["comp"] if c["mode"] == "compile"]
    need(
        imgs == load(folder / "images.json.gz")
        and info["full"] == allfull
        and info["native_links"] == imgs["wild"]
        and code == info["code"],
        "actual complete native roster differs",
    )
    sdk = Path(imgs["cargo"]["exe"]).parent.parent
    need(sdk.parts[-3:] == (".rustup", "toolchains", "ohm"), "foreign physical Cargo SDK")
    live(folder, allfull, record, sdk)
    fired = [r for r in typed if r["reason"] == "compiler-artifact"]
    diag = [
        r["message"]
        for r in typed
        if r["reason"] == "compiler-message" and r["message"]["level"] == "error"
    ]
    need(
        info["typed"] == len(fired)
        and info["allocation"]["held_sessions"] == 0
        and 0
        < info["allocation"]["unique_allocated"]
        <= sum(info["allocation"]["regular"].values()),
        "typed roster, held sessions or allocation",
    )
    for path, s in info["sessions"].items():
        m = donors.PATTERN.fullmatch(Path(path).name)
        need(
            m
            and (m[1], m[2], m[3]) == (s["time"], s["branch"], s["revision"])
            and (m[3] is None) == (role == "E")
            and s["owner"] in w.OWN
            and len(s["directory"]) == 2
            and set(s["tables"]) == set(donors.TABLES),
            "inconsistent retained session",
        )
        for kind, f in s["tables"].items():
            fp = Path(f["path"])
            need(
                fp.parent == Path(path)
                and fp.name in (kind, "ohm-packed-" + kind)
                and f["length"] > 0
                and f["blocks"] > 0
                and re.fullmatch("[0-9a-f]{64}", f["sha256"]),
                "foreign retained table metadata",
            )
    for n in w.OWN:
        need(
            sum(a["owner"] == n for a in info["sessions"].values()) <= 2,
            "third finalized generation",
        )
    if code:
        need(
            len(diag) == 1
            and diag[0]["code"]["code"] == "E0308"
            and [
                (
                    s["file_name"].removeprefix(imgs["cargo"]["cwd"] + "/"),
                    any("_AST_REAL_DONOR_ERROR" in l["text"] for l in s["text"]),
                )
                for s in diag[0]["spans"]
                if s["is_primary"]
            ]
            == [(w.LIB, True)]
            and [c["name"] for c in allfull] == [w.OWN[0]],
            "wrong real Ruff rejection",
        )
    else:
        need(not diag, "unexpected additional Ruff error")
        check_client(folder, cas, info, typed, imgs, width, flavor, tmp, execs, checked)
    return info


PROVIDER = {
    "initial-Y": (17, 2, "y"),
    "historical-X": (17, 1, "old"),
    "fast-forward-X": (17, 2, "old"),
    "unchanged-input": (17, 2, "y"),
    "same-inode-29": (29, 2, "y"),
    "malformed": ("bad", 2, "y"),
    "repair-37": (37, 2, "y"),
    "repeat-37": (37, 2, "y"),
    "empty-29": (29, 2, "y"),
    "empty-bad": ("bad", 2, "y"),
    "empty-37": (37, 2, "y"),
}


def provider(folder, role, record, rd, tmp, executed):
    terminal = {}
    history = {}
    fixed = None
    variants = {}
    need(
        {d.name for d in folder.iterdir() if d.is_dir()} == set(PROVIDER) | {"bodies"},
        "wrong native matrix",
    )
    for tag, (v, branch, label) in PROVIDER.items():
        f = folder / tag
        r = load(f / "result.json")
        code = 101 if v == "bad" else 0
        rows, im, ex, raw, stdout, stderr = cargo(
            f,
            code,
            native_provider.COMMAND,
            tag == "initial-Y" or tag.startswith("empty-"),
            record,
            rd,
            True,
        )
        ev = load(f / "file-opens.json")
        p = r["provider"]
        (held,) = ev["registered"]
        need(
            (held["dev"], held["ino"], held["length"], held["sha256"]) == (p[0], p[1], p[2], p[4])
            and Path(held["path"]).name == "libsame_revision.a"
            and p[3] == 1600000000000000000
            and im["wild"] == r["links"]
            and r["branch"] == label
            and r["exit"] == code
            and len(r["source"]) == 40,
            "native provider or actual linker changed",
        )
        if fixed is None:
            fixed = p[:4]
        need(p[:4] == fixed, "same-stat/inode condition lost")
        orig = original(folder / "bodies", r["archive"])
        need(
            [len(orig), digest(orig)] == [p[2], p[4]]
            and (v == "bad" or orig.startswith(b"!<arch>\n"))
            and variants.setdefault(v, p[4]) == p[4],
            "actual source archive mismatch",
        )
        family = native_provider.linked_families(raw, ex, im["wild"])
        observed = set()
        for e in ev["events"]:
            need((e["dev"], e["ino"], e["length"]) == tuple(p[:3]), "wrong fanotify file")
            if e["mask"] & donors.OPEN and e["pid"] in family:
                observed.add(family[e["pid"]])
        need(
            observed == set(r["observed_linkers"])
            and (observed or tag in ("unchanged-input", "repeat-37")),
            "required actual native input read missing",
        )
        if code:
            need(
                r["elf"] is None
                and r["stdout"] is None
                and not r["published_outputs"]
                and r["cargo_executable"] is None
                and b"link" in (stdout + stderr).lower(),
                "unrelated malformed failure",
            )
        else:
            (outfile,) = [a["executable"] for a in rows if a.get("executable")]
            cmd, out, err = command(f, "runtime", 0)
            need(
                cmd["argv"] == [outfile]
                and cmd["cwd"] == im["cargo"]["cwd"]
                and not err
                and out == f"{v} {branch}\n".encode()
                and r["stdout"] == out.decode()
                and r["cargo_executable"][0] == outfile
                and r["cargo_executable"][3:] == r["elf"],
                "native output path/verdict",
            )
            if tag not in ("unchanged-input", "repeat-37"):
                need(r["published_outputs"], "no successful actual output-to-link mapping")
            for pid, output, dev, ino, size, hashval in r["published_outputs"]:
                (a,) = [i["argv"] for i in im["wild"] if i["pid"] == pid]
                need(
                    pid in observed
                    and a[a.index("-o") + 1] == output
                    and dev > 0
                    and ino > 0
                    and [size, hashval] == r["elf"],
                    "wrong actual linker output",
                )
            execute(folder / "bodies", r["elf"], [], out, tmp, executed)
        terminal[tag] = [code, r["stdout"], r["elf"]]
        history[tag] = r
    for a, z in (
        ("same-inode-29", "empty-29"),
        ("malformed", "empty-bad"),
        ("repair-37", "empty-37"),
        ("repeat-37", "empty-37"),
    ):
        need(
            terminal[a] == terminal[z] and history[a]["provider"] == history[z]["provider"],
            "warm/own empty native mismatch",
        )
    need(
        len(set(variants.values())) == 4
        and history["historical-X"]["source"] != history["initial-Y"]["source"]
        and all(
            v["source"] == history["initial-Y"]["source"]
            for k, v in history.items()
            if k != "historical-X"
        )
        and load(folder / "qualified.json")
        == {"role": role, "initial": history["initial-Y"]["elf"], "terminal": terminal},
        "non-discriminating provider control or wrong terminal",
    )
    return terminal


def verify(logs, observer, tmp):
    rd = w.smoke(observer)
    scope = logs / "ordinary-ruff"
    cas = scope / "bodies"
    executed = set()
    checked = set()
    original = load(scope / "qualified.json")
    need(
        original["qualified"]
        and original["source"] == [OLD, NEW]
        and original["command"] == w.CLI
        and original["cargo"] == w.b.CARGO
        and original["observer"] == w.KERNEL
        and set(original["roles"]) == {"E", "D"},
        "foreign qualification or command",
    )
    fixed = load(logs / "ruff-inputs.json")
    need(
        fixed["commits"] == w.kit.REVS
        and fixed["trees"] == w.kit.TREES
        and len(fixed["archives"]) == 505
        and fixed["lock"] == "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb"
        and len(fixed["changed"]) == 169,
        "incomplete acquired Ruff checkout/registry",
    )
    q = logs / "donor-fixtures"
    g = q / "group"
    reread = subprocess.check_output(
        [
            sys.executable,
            "-IB",
            observer / "scripts/branch-return-execstop/group_fixtures.py",
            "reopen",
            g,
        ]
    )
    need(
        reread == body(g / "group-v2/qualified.json")
        and load(q / "toolchain.json")["fixtures"] == digest(reread)
        and json.loads(reread)["schema"] == 3,
        "actual observer on this native host",
    )
    for tag, code, n in (("true", 0, 1), ("duplicate", 19, 3), ("thread", 37, 2)):
        need(
            len(events.reopen(body(q / (tag + ".tsv")), code)["execs"]) == n,
            "original cold observer control",
        )
    sources = {}
    cases = {}
    presults = {}
    records = {}
    for role in ("E", "D"):
        folder = scope / role
        record = load(logs / "sdk" / (role + ".json"))
        records[role] = record
        arm = load(logs / ("subject-" + role) / "arm.json")
        env = arm["env"]
        need(
            arm["arm"] == role + "on"
            and arm["source_manifest"] == SOURCE_RECEIPT
            and arm["role"] == role
            and arm["files"]
            == {
                k: record["files"][k]
                for k in ("bin/cargo", "bin/rustc", "bin/rustdoc", record["driver"], w.b.WILD)
            }
            and env["CARGO_ENCODED_RUSTFLAGS"] == "-Zohm-branch-cache=yes"
            and env["CARGO_TARGET_DIR"].endswith("/work/target")
            and env["CARGO_BUILD_BUILD_DIR"].endswith("/work/build")
            and env["CARGO_NET_OFFLINE"] == "true"
            and "CI" not in env
            and "RUSTFLAGS" not in env,
            "foreign role/config",
        )
        sources[role] = [arm["sdk"], record["files"][record["driver"]][0]]
        presults[role] = provider(folder / "provider", role, record, rd, tmp, executed)
        refs = {
            s: visit(folder / ("empty-" + s), role, rd, record, cas, tmp, executed, checked, False)
            for s in ("comment", "semantic")
        }
        need(
            refs["comment"]["elf"] != refs["semantic"]["elf"],
            "actually different semantic executable",
        )
        claims = {}
        for state in ("clean", "dirty"):
            h = {
                s: visit(
                    folder / state / s,
                    role,
                    rd,
                    record,
                    cas,
                    tmp,
                    executed,
                    checked,
                    state == "dirty",
                )
                for s in w.HIST
            }
            saved = load(folder / state / "return/registered-donors.json")
            regd = donors.enrollment(h["Y-B"], h["X-A"], h["X-B"], role, w.B)
            need(regd == saved, "enrollment differs from actual newly finalized donor")
            observed = donors.verify_opens(
                saved,
                load(folder / state / "return/kernel-file-opens.json"),
                h["return"]["full"],
                role,
            )
            need(observed == h["return"]["used_donors"], "unverified actual donor selection")
            for tag in ("return", "repeat", "repair"):
                w.compare(h[tag], refs["comment"])
            w.compare(h["semantic"], refs["semantic"])
            names = [i["name"] for i in h["return"]["full"]]
            required = list(w.OWN) if role == "E" or state == "dirty" else [w.OWN[0]]
            need(
                names == required
                and not h["repeat"]["full"]
                and all(not h[k]["native_links"] for k in ("return", "repeat")),
                "wrong actual return rosters",
            )
            claims[state] = {
                "return": names,
                "repeat": [],
                "opens": observed,
                "elf": h["return"]["elf"],
                "allocation": h["return"]["allocation"],
            }
        need(
            load(folder / "qualified.json")
            == {"claims": claims, "refs": {k: v["elf"] for k, v in refs.items()}}
            and sha(folder / "qualified.json") == original["roles"][role],
            "different native terminal",
        )
        cases[role] = claims
    need(
        sources["E"][0] == sources["D"][0]
        and sources["E"][1] != sources["D"][1]
        and records["E"]["files"]["bin/cargo"][0]
        == records["D"]["files"]["bin/cargo"][0]
        == w.b.CARGO_ELF
        and records["E"]["files"][w.b.WILD][0]
        == records["D"]["files"][w.b.WILD][0]
        == w.b.WILD_ELF,
        "failed same visible SDK or pinned Cargo/Wild",
    )
    return {
        "qualified": True,
        "source": [OLD, NEW],
        "subjects": sources,
        "rosters": cases,
        "provider": presults,
        "workspace_cargo_commands": 36,
        "provider_cargo_commands": 22,
        "unique_native_reexecutions": len(executed),
        "unique_native_objects_reopened": len(checked),
        "qualification": "ordinary native correctness; no clocks or PMUs",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", type=Path)
    ap.add_argument("observer", type=Path)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="same-revision-native-readback-") as d:
        print(
            json.dumps(
                verify(args.logs.resolve(), args.observer.resolve(), Path(d)), sort_keys=True
            )
        )
