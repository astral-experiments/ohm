"""Qualify workspace reuse on real rustup and compare only the ordinary O1 Ruff linked build."""

from collections import Counter
from pathlib import Path
import gzip
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE))
spec = importlib.util.spec_from_file_location(
    "base_actual_compiler_enrollment", BASE / "measure.py"
)
actual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actual)
import builds
from provider import check as providers
from opened_driver import inspect
from decision import paid

normal, s, b, m = actual.normal, actual.s, actual.b, actual.m
R, S, O = m.R, m.S, m.O
DENY = ".ohm-worktree-seed-deny-v7"
SEED = ".ohm-worktree-seed-v7"
BAD = b'\nconst _: u8 = "OHM_LINKED_RUST_E0308";\n'
CMD = builds.COMMAND
role_name = {"P": "parent", "C": "candidate"}


def identity(p):
    return {"path": str(p.resolve()), "sha256": m.sha(p), "node": actual.stamp(p)}


def parse_cargo(stdout, rc):
    rows = [json.loads(x) for x in stdout.splitlines()]
    assert rows[-1] == {"reason": "build-finished", "success": rc == 0}
    errors = [
        r["message"] for r in rows if r.get("message", {}).get("level") == "error"
    ]
    assert bool(errors) == bool(rc)
    return rows, errors


def artifacts(rows):
    return [v for v in rows if v["reason"] == "compiler-artifact"]


def marks(env):
    files = {}
    for top in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"):
        d = Path(env[top])
        assert d.is_dir()
        for name in (SEED, DENY):
            for f in d.rglob(name):
                assert f.is_file() and not f.is_symlink() and f.stat().st_size < 1024
                files[str(f)] = {"bytes": f.read_bytes().decode(), "sha256": m.sha(f)}
    return files


def marker_check(found, denied):
    yes = [(p, v) for p, v in found.items() if Path(p).name == SEED]
    no = [(p, v) for p, v in found.items() if Path(p).name == DENY]
    assert len(yes) == 1 and len(no) == int(denied), found
    if denied:
        assert no[0][1]["bytes"] == "untrusted compile-time inputs\n"


def working_generator(rows):
    which = [
        u
        for u in artifacts(rows)
        if u["target"]["kind"] == ["custom-build"]
        and "/crates/ruff_unicode_names2#" in u["package_id"]
    ]
    (u,) = which
    (p,) = [
        Path(a)
        for a in u["filenames"]
        if Path(a).name in ("build-script-build", "build_script_build")
    ]
    (out,) = [
        Path(v["out_dir"])
        for v in rows
        if v["reason"] == "build-script-executed" and v["package_id"] == u["package_id"]
    ]
    data = {f.name: m.sha(f) for f in out.glob("*.rs")}
    assert data == actual.common_generated
    archive = O / "generated"
    archive.mkdir(exist_ok=True)
    for name, digest in data.items():
        dest = archive / (digest + ".gz")
        if not dest.exists():
            m.gz(dest, (out / name).read_bytes())
        assert m.h(gzip.decompress(dest.read_bytes())) == digest
    return p, data


def new_file(p, contents):
    with p.open("xb") as out:
        out.write(contents)


def compilation_argv(line):
    if (
        b'"--crate-name"' not in line
        or b'"--out-dir"' not in line
        or re.search(rb'"--print(?:=|")', line)
    ):
        return None
    # strace prints ordinary Rust compilation operands as a JSON-compatible string array.
    complete = re.match(rb'^execve\("[^"]+", ', line)
    assert complete and line.rstrip().endswith(b"= 0")
    text = os.fsdecode(line[complete.end() :])
    args, end = json.JSONDecoder().raw_decode(text)
    assert text[end:].startswith(", [") and all(isinstance(v, str) for v in args)
    return args


def capture(where, args, env, cwd, expected=0):
    where.mkdir(parents=True)
    temp = where / "original-pid-traces"
    temp.mkdir()
    command = [
        "strace",
        "-ff",
        "-qq",
        "-v",
        "-s",
        "65536",
        "-e",
        "trace=execve,openat,openat2",
        "-o",
        str(temp / "pid"),
        *map(str, args),
    ]
    res = subprocess.run(command, env=env, cwd=cwd, capture_output=True, timeout=300)
    m.gz(where / "stdout.gz", res.stdout)
    m.gz(where / "stderr.gz", res.stderr)
    wild = []
    compilers = []
    script_env = []
    scripts = []
    files = sorted(temp.glob("pid.*"))
    seen = where / "all-process-opens.gz"
    match = lambda p, f: p.is_file() and p.samefile(f)
    with gzip.open(seen, "xb", compresslevel=1) as gz:
        for p in files:
            pid = int(p.name.split(".")[-1])
            with p.open("rb") as fh:
                for ln in fh:
                    gz.write(str(pid).encode() + b" " + ln)
                    v = re.match(rb'^execve\("([^"]+)",', ln)
                    if not (v and ln.rstrip().endswith(b"= 0")):
                        continue
                    image = Path(os.fsdecode(v[1]))
                    if match(image, b.rust):
                        a = compilation_argv(ln)
                        if a is not None:
                            compilers.append({"pid": pid, "argv": a})
                    if match(image, b.wild):
                        o = re.search(rb'", "-o", "([^"]+)"', ln)
                        assert o
                        wild.append([pid, os.fsdecode(o[1])])
                    if image.name in ("build_script_build", "build-script-build"):
                        arr = re.findall(
                            rb'"((?:RUSTDOC|RUSTUP_HOME|RUSTUP_TOOLCHAIN)=[^"]*)"', ln
                        )
                        script_env.append([pid, str(image), [v.decode() for v in arr]])
                        scripts.append(str(image))
            p.unlink()
    temp.rmdir()
    (driver,) = (b.sdk / "lib").glob("librustc_driver*.so")
    with gzip.open(seen, "rb") as f:
        rustcs = inspect(f, lambda p: match(p, b.rust), lambda p: match(p, driver))
    assert sorted(
        [x["pid"], x["argv"][x["argv"].index("--crate-name") + 1]] for x in compilers
    ) == [[pid, crate] for pid, crate, _ in rustcs]
    vals = {
        "argv": command,
        "code": res.returncode,
        "physical_wild": wild,
        "physical_compilers": rustcs,
        "compiler_argv": compilers,
        "driver": identity(driver),
        "script_executions": scripts,
        "selected_script_environments": script_env,
        "trace_sha256": m.sha(seen),
    }
    m.save(where / "kernel.json", vals)
    assert res.returncode == expected
    rows, _ = parse_cargo(res.stdout, expected)
    return rows, vals


def tiny(where, env, expect_denied):
    project = R / "tiny-marker-project"
    if not project.exists():
        (project / "src").mkdir(parents=True)
        new_file(
            project / "Cargo.toml",
            b'[package]\nname="native_layout_probe"\nversion="0.1.0"\nedition="2024"\n[workspace]\n',
        )
        new_file(
            project / "Cargo.lock",
            b'version = 4\n\n[[package]]\nname = "native_layout_probe"\nversion = "0.1.0"\n',
        )
        new_file(
            project / "build.rs",
            b'fn main(){println!("cargo:rerun-if-changed=build.rs");std::fs::write(std::path::Path::new(&std::env::var_os("OUT_DIR").unwrap()).join("value.rs"),"47u8").unwrap();}\n',
        )
        new_file(
            project / "src/lib.rs",
            b'pub const READER: u8 = include!(concat!(env!("OUT_DIR"),"/value.rs"));\n',
        )
    slot = R / ("tiny-" + where)
    assert not slot.exists()
    e = env | {
        "CARGO_TARGET_DIR": str(slot / "target"),
        "CARGO_BUILD_BUILD_DIR": str(slot / "shared"),
    }
    cmd = "cargo +ohm build --lib --locked --offline -j1 --message-format=json".split()
    d = O / "layout" / where
    rows, phys = capture(d, cmd, e, project)
    assert sorted(v[1] for v in phys["physical_compilers"]) == [
        "build_script_build",
        "native_layout_probe",
    ]
    (script,) = phys["selected_script_environments"]
    assert any("RUSTDOC=" in v for v in script[2])
    (v,) = [q for q in rows if q["reason"] == "build-script-executed"]
    assert (Path(v["out_dir"]) / "value.rs").read_bytes() == b"47u8"
    files = marks(e)
    sd = b.sdk / "bin/rustdoc"
    out = {
        "expected_denied": expect_denied,
        "markers": files,
        "sdk": str(b.sdk.resolve()),
        "RUSTDOC_explicit": e.get("RUSTDOC"),
        "physical_sysroot": m.get(["rustc", "+ohm", "--print", "sysroot"], env=e)
        .decode()
        .strip(),
        "own_sdk_has_rustdoc": sd.is_file(),
        "actual_script_env": script,
        "packages": [q["package_id"] for q in artifacts(rows)],
    }
    m.save(d / "layout.json", out)
    marker_check(files, expect_denied)
    if not sd.exists():
        assert "RUSTDOC=rustdoc" in script[2]
    assert slot.parent == R and not slot.is_symlink()
    shutil.rmtree(slot)
    return out


def place(kits, env):
    first = kits.active
    assert first in "PC" and not any((S / n).exists() for n in ("target", "shared"))
    kits.assert_binaries(first)
    old = b.sdk
    depot = actual.BOX / role_name[first]
    assert not depot.exists()
    old.rename(depot)
    kits.active = None
    home = R / "private-rustup-user"
    bins = home / ".cargo/bin"
    bins.mkdir(parents=True)
    proxy = Path(shutil.which("rustup", path=env["PATH"])).resolve(strict=True)
    for name in ("cargo", "rustc", "rustdoc"):
        assert Path(shutil.which(name, path=env["PATH"])).samefile(proxy), name
    copied = bins / "rustup"
    shutil.copy2(proxy, copied)
    assert m.sha(copied) == m.sha(proxy)
    for name in ("cargo", "rustc", "rustdoc"):
        os.link(copied, bins / name)
    home_rust = home / ".rustup"
    stable = home_rust / "toolchains/ohm"
    stable.parent.mkdir(parents=True)
    e = env | {
        "HOME": str(home),
        "RUSTUP_HOME": str(home_rust),
        "PATH": str(bins) + os.pathsep + env["PATH"],
    }
    assert not (actual.FORBID | {"RUSTC", "RUSTDOC", "RUSTUP_TOOLCHAIN"}) & e.keys()
    for nm in ("cargo", "rustc", "rustdoc", "rustup"):
        assert Path(shutil.which(nm, path=e["PATH"])).samefile(copied)
    b.sdk = stable
    b.cargo = stable / "bin/cargo"
    b.rust = stable / "bin/rustc"
    b.wild = stable / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    # A legacy evidence helper locates the signed linker through this spare path; the active compiler is always the physical rustup tree.
    old.symlink_to(stable, target_is_directory=True)
    kits.env = e
    m.save(
        O / "physical-layout.json",
        {
            "source_rustup": identity(proxy),
            "private_rustup": identity(copied),
            "proxies": {
                nm: identity(bins / nm) for nm in ("cargo", "rustc", "rustdoc")
            },
            "physical_sdk": str(stable),
            "compatibility_tool_lookup": str(old),
            "environment": e,
        },
    )
    kits.select(first, "1")
    assert (
        not stable.is_symlink()
        and stable.resolve() == stable
        and (old / "bin/rustc").samefile(b.rust)
    )
    return e


def host_group(prog, state, role, env):
    values = []
    for j in range(2):
        prefix = O / "component" / role / state / str(j)
        prefix.mkdir(parents=True)
        output = R / ("component-" + role + "-" + state + "-" + str(j))
        output.mkdir()
        e = env | {"OUT_DIR": str(output)}
        cwd = m.src / "crates/ruff_unicode_names2"
        exe = prog.resolve(strict=True)
        args = [R / "watch", prefix / "whole.json", exe]
        r = subprocess.run(args, env=e, cwd=cwd, capture_output=True, timeout=120)
        m.gz(prefix / "stdout.gz", r.stdout)
        m.gz(prefix / "stderr.gz", r.stderr)
        c = m.read(prefix / "whole.json")
        files = {f.name: m.sha(f) for f in output.iterdir()}
        assert r.returncode == c["code"] == 0 and files == actual.common_generated
        m.save(
            prefix / "result.json",
            {
                "elf": identity(exe),
                "generated": files,
                "scope": "real generator alone, outside Cargo",
                "argv": list(map(str, args)),
                "cwd": str(cwd),
                "out_dir": str(output),
            },
        )
        values.append(c["instructions"] if b.hw(c) else None)
    return values


def src_states():
    path = m.src / builds.PATH
    current = path.read_bytes()
    assert (
        m.h(current)
        == "9e66456a0167e332cd50175f529708362c2fa2ce1f5c17daf34d3b87c2e46669"
        and current.count(builds.NEW) == 1
        and builds.OLD not in current
    )
    m.w.git(
        m.src,
        "fetch",
        "-q",
        "--no-tags",
        "--depth=2",
        "https://github.com/astral-sh/ruff.git",
        builds.HIST,
    )
    old = m.w.git(m.src, "show", builds.HIST + "^:" + builds.PATH)
    new = m.w.git(m.src, "show", builds.HIST + ":" + builds.PATH)
    assert (
        old.count(builds.OLD) == new.count(builds.NEW) == 1
        and builds.NEW not in old
        and builds.OLD not in new
    )
    return path, {"new": current, "old": current.replace(builds.NEW, builds.OLD)}


def stage_roster(compilers, roster):
    sources = []
    generators = []
    for row in compilers:
        a = row["argv"]
        assert not any("share-generics" in x for x in a)
        if "-Zohm-shared-stages" not in a:
            continue
        src = next(x for x in a if x.endswith(".rs") and not x.startswith("-"))
        sources.append(src.split("/registry/src/", 1)[-1])
        if src == normal.SOURCE:
            assert "--emit=dep-info,metadata,link" in a and "--target" not in a
            generators.append(row)
    observed = {
        "actual_full": len(compilers),
        "stage_sources": sorted(sources),
        "workspace": sum(v.startswith("crates/") for v in sources),
    }
    assert observed == normal.prior[roster], (roster, observed, normal.prior[roster])
    return generators


def component_summary(econs, entities, orientation):
    return {
        "component_counts": econs,
        "component_P_over_C": {
            state: [
                p / c if p and c else None
                for p, c in zip(econs["P"][state], econs["C"][state])
            ]
            for state in orientation
        },
        "generator_elf": entities,
        "qualification": "descriptive only; the whole Cargo command determines the decision",
    }


def preflight(kits, env, order, orientation):
    gp, text = src_states()
    original = gp.read_bytes()
    econs = {}
    data = {}
    try:
        for role in order:
            b.clear()
            kits.select(role, "1")
            selected = {}
            for i, state in enumerate(orientation):
                gp.write_bytes(text[state])
                seq = ("cold", "repeat") if i == 0 else ("real-edit",)
                for visit in seq:
                    d = O / "real-driver-admission" / role / visit
                    rows, raw = capture(d, CMD, env, m.src)
                    physical = raw["physical_compilers"]
                    pro, gen = working_generator(rows)
                    marker = marks(env)
                    script = [
                        x
                        for x in raw["selected_script_environments"]
                        if Path(x[1]).samefile(pro)
                    ]
                    (ran,) = script
                    count = Counter(x[1] for x in physical)
                    assert len(raw["physical_wild"]) == 1 and Path(
                        raw["physical_wild"][0][1]
                    ).samefile(pro)
                    assert (
                        "RUSTDOC=rustdoc" in ran[2]
                        and raw["driver"]["sha256"] == actual.DRIVERS[role_name[role]]
                    )
                    perf = {
                        "compiler": role,
                        "source": state,
                        "source_sha256": m.sha(gp),
                        "crate_counts": dict(count),
                        "marker": marker,
                        "generated": gen,
                        "generator": s.keep_elf(
                            pro, "new-supported-" + role + "/" + visit
                        ),
                        "expected_admission": "17/1 cold and 1/1 true unchanged",
                    }
                    m.save(d / "observation.json", perf)
                    marker_check(marker, False)
                    if visit == "cold":
                        named = stage_roster(raw["compiler_argv"], "build-cold")
                        assert (
                            len(physical) == 17
                            and count["unicode_names2_generator"]
                            == count["unicode_names2"]
                            == count["build_script_build"]
                            == 1
                        )
                        assert [r["pid"] for r in named] == [
                            p
                            for p, crate, _ in physical
                            if crate == "unicode_names2_generator"
                        ]
                        settings_dir = O / "effective-settings" / role
                        settings_dir.mkdir(parents=True)
                        actual.settings_probe(
                            settings_dir,
                            env,
                            "1",
                            {
                                "kernel": {
                                    "selected": {"unicode_names2_generator": named}
                                }
                            },
                        )
                    elif visit == "repeat":
                        assert not stage_roster(raw["compiler_argv"], "build-repeat")
                        assert (
                            len(physical) == 1
                            and count["build_script_build"] == 1
                            and perf["generator"]["sha256"] == selected[state][0]
                        )
                    else:
                        assert (
                            count["unicode_names2_generator"]
                            == count["build_script_build"]
                            == 1
                        )
                    selected[state] = [perf["generator"]["sha256"], pro]
                econs.setdefault(role, {})[state] = host_group(
                    selected[state][1], state, role, env
                )
            data[role] = {n: v[0] for n, v in selected.items()}
            kits.assert_binaries(role)
            b.clear()
    finally:
        gp.write_bytes(original)
    m.save(O / "component.json", component_summary(econs, data, orientation))


def valid_after_error(rows, env, d):
    _, files = working_generator(rows)
    candidates = [
        q
        for q in artifacts(rows)
        if q["target"]["kind"] == ["lib"] and q["target"]["name"] == "unicode_names2"
    ]
    (target,) = candidates
    (rlib,) = [Path(f) for f in target["filenames"] if f.endswith(".rlib")]
    place = R / "reader-stable"
    reader = place / "reader"
    source = place / "reader.rs"
    assert source.read_bytes() == builds.READER
    dirs = sorted(
        {
            p.parent
            for root in (S / "target", S / "shared")
            for mode in ("*.rlib", "*.rmeta")
            for p in root.rglob(mode)
        }
    )
    argv = [
        "rustc",
        "+ohm",
        "--edition=2024",
        source,
        "--extern",
        "unicode_names2=" + str(rlib),
        *["-Ldependency=" + str(k) for k in dirs],
        "-o",
        reader,
    ]
    m.run(argv, env=env)
    observed = m.get([reader], env=env).decode()
    facts = {
        "reader": s.keep_elf(reader, str(d.relative_to(O))),
        "verdict": observed,
        "generated": files,
        "target_rlib_sha256": m.sha(rlib),
        "argv": list(map(str, argv)),
    }
    m.save(d / "returned.json", facts)
    assert (
        files == actual.common_generated
        and observed == "Some(0)\nSome(0)\nSome(65)\nSome(9731)\n"
    )
    return facts["reader"]["sha256"]


def reader_gate(d):
    phases = (
        "cold",
        "neutral-unchanged",
        "historical-hunk",
        "first-unchanged",
        "traced-repeat",
        "independent-empty",
    )
    rows = {p: m.read(d / p / "build.json") for p in phases}
    assert all(
        r["generated"] == actual.common_generated
        and r["reader"] == "Some(0)\nSome(0)\nSome(65)\nSome(9731)\n"
        for r in rows.values()
    )
    for group in (phases[:2], phases[2:]):
        for name in group:
            assert rows[name]["source"] == rows[group[0]]["source"]
            assert (
                rows[name]["reader_elf"]["sha256"]
                == rows[group[0]]["reader_elf"]["sha256"]
            )
    assert rows["cold"]["source"] != rows["historical-hunk"]["source"]
    for group in (phases[:2], phases[2:5]):
        assert len({rows[name]["rlib"][1] for name in group}) == 1
    return {
        name: {
            "source": r["source"],
            "reader": r["reader_elf"]["sha256"],
            "rlib": r["rlib"][1],
        }
        for name, r in rows.items()
    }


def errors(kits, env, order, final):
    gp, versions = src_states()
    good = gp.read_bytes()
    subject = m.src / "crates/ruff_unicode_names2/src/lib.rs"
    base = subject.read_bytes()
    bad = base + BAD
    reader_place = R / "reader-stable"
    reader_place.mkdir()
    new_file(reader_place / "reader.rs", builds.READER)
    try:
        gp.write_bytes(versions[final])
        for role in order:
            b.clear()
            kits.select(role, "1")
            seen = []
            success = {}
            for receipt, sequence in (
                ("warm", ("ready", "invalid", "repair")),
                ("empty", ("invalid", "repair")),
            ):
                b.clear()
                for ph in sequence:
                    d = O / "invalid-repair" / role / receipt / ph
                    d.mkdir(parents=True)
                    subject.write_bytes(bad if ph == "invalid" else base)
                    rc = 101 if ph == "invalid" else 0
                    p = subprocess.run(
                        CMD, env=env, cwd=m.src, capture_output=True, timeout=240
                    )
                    m.gz(d / "stdout.gz", p.stdout)
                    m.gz(d / "stderr.gz", p.stderr)
                    rows, diagnostics = parse_cargo(p.stdout, rc)
                    m.save(
                        d / "source.json",
                        {
                            "file": str(subject.relative_to(m.src)),
                            "source_sha": m.sha(subject),
                            "cargo_exit": p.returncode,
                            "errors": diagnostics,
                        },
                    )
                    assert rc == p.returncode
                    if rc:
                        (e,) = diagnostics
                        assert e["code"]["code"] == "E0308" and any(
                            v["is_primary"]
                            and v["file_name"]
                            == "crates/ruff_unicode_names2/src/lib.rs"
                            and "OHM_LINKED_RUST_E0308"
                            in "".join(t["text"] for t in v["text"])
                            for v in e["spans"]
                        )
                        seen.append(e)
                    else:
                        success[receipt + "/" + ph] = valid_after_error(rows, env, d)
            assert len(seen) == 2 and seen[0] == seen[1]
            assert len(success) == 3 and len(set(success.values())) == 1
            m.save(
                O / "invalid-repair" / role / "valid-from-empty-and-repair.json",
                {"generator_source": m.sha(gp), "reader_elf": success},
            )
            b.clear()
            kits.assert_binaries(role)
    finally:
        subject.write_bytes(base)
        gp.write_bytes(good)
    assert reader_place.parent == R and not reader_place.is_symlink()
    assert {p.name for p in reader_place.iterdir()} == {"reader", "reader.rs"}
    shutil.rmtree(reader_place)


def decision():
    visits = ("cold", "neutral-unchanged", "historical-hunk", "first-unchanged")
    scores = {}
    for i, role in enumerate("PC"):
        root = O / "ordinary-lib" / ("opt" + str(i))
        scores[role] = {ph: paid(root / ph, "build") for ph in visits}
        scores[role]["edit-plus-repeat"] = [
            scores[role]["historical-hunk"][0] + scores[role]["first-unchanged"][0],
            scores[role]["first-unchanged"][1],
        ]
    comparisons = {}
    for phase, (parent_ir, parent_bytes) in scores["P"].items():
        child_ir, child_bytes = scores["C"][phase]
        comparisons[phase] = {
            "parent_instructions": parent_ir,
            "candidate_instructions": child_ir,
            "parent_over_candidate": parent_ir / child_ir,
            "parent_fresh_store_allocated_B": parent_bytes,
            "candidate_fresh_store_allocated_B": child_bytes,
            "candidate_minus_parent_allocated_B": child_bytes - parent_bytes,
        }
    cold = comparisons["cold"]
    primary = ("first-unchanged", "edit-plus-repeat")
    return {
        "source_profile": "both fixed O1",
        "complete_whole_Cargo": comparisons,
        "over_1_8_this_host": [
            k for k in primary if comparisons[k]["parent_over_candidate"] >= 1.8
        ],
        "over_2_this_host": [
            k for k in primary if comparisons[k]["parent_over_candidate"] >= 2
        ],
        "cold_more_than_5pct": cold["candidate_instructions"]
        > 1.05 * cold["parent_instructions"],
        "fresh_more_than_8MiB_or_1pct": (
            cold["candidate_minus_parent_allocated_B"] > 8 * 2**20
            or cold["candidate_fresh_store_allocated_B"]
            > 1.01 * cold["parent_fresh_store_allocated_B"]
        ),
    }


def main():
    row = os.environ["QA_ROW"]
    order = ("P", "C") if row == "01" else ("C", "P")
    orientation = ("new", "old") if row == "01" else ("old", "new")
    env = b.procure()
    for k in ("subjects", "strict"):
        (O / (k + ".json")).rename(O / ("signed-acquisition-" + k + ".json"))
    m.save(
        O / "enrollment.json",
        {
            "row": row,
            "head": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
            "host": os.uname().nodename,
            "plan": m.sha(HERE / "PLAN.md"),
            "source": m.c.RUFF,
            "historical_hunk": builds.HIST,
            "cmd": CMD,
            "order": order,
            "states": orientation,
            "profile": actual.config("1").decode(),
            "seal": actual.SEAL,
        },
    )
    actual.settings(env, "1")
    tiny("signed-arbitrary", env, False)
    kits = actual.Toolchains(env)
    kits.select(order[0], "1")
    unsupported = tiny("source-arbitrary-" + order[0], env, True)
    assert not unsupported["own_sdk_has_rustdoc"] and unsupported[
        "physical_sysroot"
    ] == str(b.sdk)
    env = place(kits, env)
    for role in order:
        kits.select(role, "1")
        tested = tiny("source-supported-" + role, env, False)
        assert not tested["own_sdk_has_rustdoc"] and tested["physical_sysroot"] == str(
            b.sdk
        )
        observed_env = tested["actual_script_env"][2]
        assert (
            "RUSTUP_HOME=" + env["RUSTUP_HOME"] in observed_env
            and "RUSTUP_TOOLCHAIN=ohm" in observed_env
        )
    preflight(kits, env, order, orientation)
    errors(kits, env, order, orientation[-1])
    # The existing provider observer locates the Cargo proxy on the Python parent's PATH.
    with patch.dict(os.environ, {"PATH": env["PATH"]}):
        assert Path(shutil.which("rustup")).samefile(
            Path(env["HOME"]) / ".cargo/bin/rustup"
        )
        providers(
            m,
            b.load,
            b.NATIVE,
            env,
            lambda e, i: kits.select("PC"[int(i)], "1"),
            b.wild,
        )
    assert (
        (R / "sdk-21").is_symlink()
        and (R / "sdk-21/bin/cargo").samefile(b.cargo)
        and not b.wild.with_name("libutil.so").exists()
    )
    for d in (S / "shared", S / "target"):
        assert not d.exists()
    m.save(
        O / "safety-admission.json",
        {
            "ordinary_source_errors_and_repairs": True,
            "verified_native_provider_histories": True,
            "published_stage_rosters": True,
        },
    )
    code = "".join(str("PC".index(short)) for short in order)
    direction = "reverse" if row == "01" else "forward"
    builds.study(
        b, env, lambda e, i: kits.select("PC"[int(i)], "1"), s.keep_elf, direction, code
    )
    for i, role in enumerate("PC"):
        kits.select(role, "1")
        d = O / "ordinary-lib" / ("opt" + str(i))
        normal.trace(d / "traced-repeat", "B", "build-repeat")
        normal.trace(d / "independent-empty", "B", "build-cold")
        returned = reader_gate(d)
        reference = m.read(
            O / "invalid-repair" / role / "valid-from-empty-and-repair.json"
        )
        assert reference["generator_source"] == returned["independent-empty"]["source"]
        assert set(reference["reader_elf"].values()) == {
            returned["independent-empty"]["reader"]
        }
        m.save(d / "qualified-readers.json", returned)
        m.save(d / "runtime.json", kits.use[-1])
    kits.assert_binaries(kits.active)
    m.save(O / "all-selections.json", kits.use)
    m.save(O / "paired-instructions.json", decision())
    m.save(
        O / "complete.json",
        {
            "row": row,
            "physical_SDK": str(b.sdk),
            "states": orientation,
            "structural_gate": True,
            "within_role_own_empty": True,
            "invalid_and_native_provider": True,
            "component_scope": "descriptive; no eligibility threshold",
        },
    )


if __name__ == "__main__":
    main()
