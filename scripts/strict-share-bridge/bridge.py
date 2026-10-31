"""Four fresh compiler modes, matched immutable handoff, untraced complete Cargo measurements."""

from pathlib import Path
import gzip, hashlib, json, os, shutil, subprocess, sys

HERE = Path(__file__).resolve().parent
root = Path(os.environ["GITHUB_WORKSPACE"])
original = root / "one"
assert (
    subprocess.check_output(["git", "-C", original, "rev-parse", "HEAD"]).decode().strip()
    == "3c9c82bb960564dbe3b0df7c0a736662354e502d"
)
sys.path.insert(0, str(original / "scripts/strict-one-package"))
import single as s

b = s.b
m = s.m
S = m.S
R = m.R
O = m.O
row = os.environ["QA_ROW"]
sequence = {"01": "ABQC", "02": "CQBA"}[row]
direction = "reverse" if row == "01" else "forward"
flag = "-Zshare-generics=no"
generator_source = "crates/ruff_unicode_names2_generator/src/lib.rs"
wrapper = R / "bridge-workspace-rustc"
upper = {"A": 0, "B": 1, "Q": 1, "C": 2}


def j(p):
    return json.loads(p.read_bytes())


def configure(env, which):
    p = Path(env["CARGO_HOME"]) / "config.toml"
    assert (
        p.parent == S / "cargo-home" and not (p.parent / "config").exists() and not p.is_symlink()
    )
    allowed = {
        n: f"[profile.dev.package.ruff_unicode_names2_generator]\nopt-level = {n}\n".encode()
        for n in (1, 2)
    }
    if p.exists():
        assert p.read_bytes() in allowed.values()
    wanted = upper[which]
    env["OHM_BRIDGE_ARM"] = which
    if not wanted:
        p.unlink(missing_ok=True)
    elif not p.exists() or p.read_bytes() != allowed[wanted]:
        temporary = p.with_name("bridge-configuration-incoming")
        assert not temporary.exists()
        temporary.write_bytes(allowed[wanted])
        temporary.replace(p)
    assert (p.read_bytes() if p.exists() else None) == allowed.get(wanted) and env[
        "RUSTC_WORKSPACE_WRAPPER"
    ] == str(wrapper)
    return env


def retained(where, arm):
    gen = s.generator(where, "check/" + arm + "/" + where.name)
    stream = s.stdout(where)
    (a,) = [
        e
        for e in stream
        if e["reason"] == "compiler-artifact"
        and e["target"]["name"] == "unicode_names2_generator"
        and e["target"]["kind"] == ["lib"]
        and "/crates/ruff_unicode_names2_generator#" in e["package_id"]
    ]
    (rlib,) = [Path(f) for f in a["filenames"] if f.endswith(".rlib")]
    raw = rlib.read_bytes()
    assert raw[:8] == b"!<arch>\n"
    archive = O / "bridge-rlibs"
    archive.mkdir(exist_ok=True)
    digest = m.h(raw)
    dest = archive / (digest + ".gz")
    if not dest.exists():
        m.gz(dest, raw)
    m.save(
        where / "held-generator-rlib.json",
        {
            "sha256": digest,
            "bytes": len(raw),
            "allocated": rlib.stat().st_blocks * 512,
            "path": str(rlib),
            "cargo_profile": a["profile"],
        },
    )
    return gen["sha256"], digest


def verify_trace(where, arm, require_gen_compile):
    rows = m.argv(where / "kernel")
    wrapstat = wrapper.stat()
    ruststat = b.rust.stat()
    wid = [wrapstat.st_dev, wrapstat.st_ino]
    rid = [ruststat.st_dev, ruststat.st_ino]
    ins = {}
    outs = {}
    actual = []
    for pid, ident, _, image, argv in rows:
        if ident == wid:
            assert pid not in ins and len(argv) > 2 and image == str(wrapper)
            ins[pid] = argv
        if ident == rid:
            assert pid not in outs
            outs[pid] = argv
            if (
                "--crate-name" in argv
                and "--out-dir" in argv
                and not any(x.startswith("--print") for x in argv)
            ):
                actual.append((pid, argv))
    assert ins and set(ins) <= set(outs)
    adjustments = []
    selected = []
    allflag = []
    for pid, argv in outs.items():
        if (
            "--crate-name" in argv
            and argv[argv.index("--crate-name") + 1] == "unicode_names2_generator"
            and generator_source in argv
        ):
            assert "--emit=dep-info,metadata,link" in argv and "--target" not in argv and pid in ins
            selected.append(pid)
        additions = [v for v in argv if "share-generics" in v]
        if additions:
            assert additions == [flag] and pid in selected and arm == "Q"
            allflag.append(pid)
        if pid in ins:
            incoming = ins[pid]
            inargs = incoming[2:]
            assert not any("share-generics" in v for v in inargs)
            extra = [flag] if arm == "Q" and pid in selected else []
            assert argv[1:] == inargs + extra, (pid, incoming[:8], argv[:8], extra)
            adjustments.append([pid, len(inargs), extra])
    assert len(selected) == int(require_gen_compile) and len(allflag) == int(
        require_gen_compile and arm == "Q"
    )
    if selected:
        arg = outs[selected[0]]
        info = b.argspec(arg)
        assert info["opt"] == str(upper[arm]) and info["debug"] == info["overflow"] == "on"
    off = [
        (p, a) for p, a in actual if not (p in selected) and any("share-generics" in v for v in a)
    ]
    assert not off
    bscript = [p for p, a in actual if "crates/ruff_unicode_names2/build.rs" in a]
    assert len(bscript) == 1 and bscript[0] in ins and b.argspec(outs[bscript[0]])["opt"] == "0"
    rec = j(where / "visit.json")
    k = rec["kernel"]
    assert (
        len(k["generators"]) == 1
        and len([v for v in k["links"] if v[1] == k["generators"][0][1]]) == 1
    )
    if arm == "A":
        names = sorted(a[a.index("--crate-name") + 1] for _, a in actual)
        if require_gen_compile:
            assert len(names) == 304 and len(k["links"]) == 48
        else:
            assert names == ["build_script_build", "ron", "unicode_names2"] and len(k["links"]) == 1
    sgen = j(where / "neutral-generator.json")
    assert k["generators"][0][1] == sgen["path"]
    m.save(
        where / "handoff.json",
        {
            "arm": arm,
            "real_rustc": rid,
            "wrapper": wid,
            "wrapped": adjustments,
            "selected": selected,
            "flag_pids": allflag,
            "other_signed_compilers": len(actual) - len(selected),
            "emitting_build_rustc": bscript,
            "signed_Wilds": k["links"],
            "actual_generator": k["generators"],
            "unwrapped_rustcs": sorted(set(outs) - set(ins)),
        },
    )
    return k


def probes(arm, env, cold):
    selected = cold["kernel"]["selected"]
    args = selected["unicode_names2_generator"][0]["argv"]
    opts = b.argspec(args)["options"]
    extra = [flag] if flag in args else []
    assert bool(extra) == (arm == "Q")
    d = R / ("bridge-checked-" + arm)
    d.mkdir()
    source = d / "probe.rs"
    source.write_text(
        'fn main(){std::panic::set_hook(Box::new(|_|{})); let v=std::hint::black_box(255u8); println!("{} {} {}",cfg!(debug_assertions),std::panic::catch_unwind(|| debug_assert!(std::hint::black_box(false))).is_err(),std::panic::catch_unwind(|| v+std::hint::black_box(1)).is_err());}\n'
    )
    binary = d / "probe"
    argv = [
        "rustc",
        "+ohm",
        "--edition=2024",
        source,
        "-o",
        binary,
        *[v for k, x in sorted(opts.items()) for v in ("-C", k + "=" + x)],
        *extra,
    ]
    m.run(argv, env=env)
    res = m.get([binary], env=env)
    assert res == b"true true true\n"
    m.save(
        O / ("opt" + arm) / "effective-settings.json",
        {
            "supplied_argv": list(map(str, argv)),
            "stdout": res.decode(),
            "elf": m.sha(binary),
            "actual_scope": args,
            "debug": b.argspec(args),
        },
    )


def main():
    env = b.procure()
    m.run(
        ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", HERE / "forward.c", "-o", wrapper]
    )
    assert wrapper.is_file()
    st = wrapper.stat()
    env |= {
        "RUSTC_WORKSPACE_WRAPPER": str(wrapper),
        "OHM_BRIDGE_RUSTC": str(b.rust),
        "OHM_BRIDGE_RUFF": str(m.src),
        "OHM_BRIDGE_ARM": "A",
    }
    m.save(
        O / "bridge.json",
        {
            "head": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
            "row": row,
            "sequence": list(sequence),
            "source_direction": direction,
            "wrapper": {
                "path": str(wrapper),
                "sha256": m.sha(wrapper),
                "dev_ino": [st.st_dev, st.st_ino],
                "ctime_ns": st.st_ctime_ns,
                "source": m.sha(HERE / "forward.c"),
            },
            "environment": env,
            "plan_sha": m.sha(HERE / "PLAN.md"),
            "exact_argv": m.cmd,
        },
    )
    m.gz(O / "forward-ELF.gz", wrapper.read_bytes())
    shutil.copy2(HERE / "forward.c", O / "forward.c")
    baseline = b.consumer.read_bytes()
    before = direction == "forward"
    srcs = []
    diags = []
    bodies = []
    inventories = []
    expected = set()
    summary = {}
    for arm in sequence:
        b.clear()
        assert not (S / "target").exists() and not (S / "shared").exists()
        b.edited(before)
        configure(env, arm)
        assert wrapper.stat().st_ino == st.st_ino and wrapper.stat().st_ctime_ns == st.st_ctime_ns
        folders = O / ("opt" + arm)
        folders.mkdir()
        graph = m.get([*m.cmd[:-1], "--unit-graph", "-Zunstable-options"], cwd=m.src, env=env)
        m.gz(folders / "unit-graph.json.gz", graph)
        images = []
        libraries = []
        measured = {}

        def visit(label, mode="score", rc=0):
            assert env["OHM_BRIDGE_ARM"] == arm
            v = b.visit(arm, label, env, mode, rc)
            gen, rlib = retained(folders / label, arm)
            images.append(gen)
            libraries.append(rlib)
            bodies.append(v["generated"])
            if not rc:
                inventories.append(v["logical_sha"])
                expected.add(tuple(v["warning_sha"]))
            if mode == "score":
                measured[label] = {
                    "whole": v["instructions"],
                    "unique_target_shared": v["storage"]["allocated_B"],
                    "dirty": len(v["dirty"]),
                }
            if mode == "trace":
                verify_trace(folders / label, arm, label == "empty-edited")
            return v

        cold = visit("cold")
        visit("neutral-unchanged")
        b.edited(not before)
        edit = visit("historical-edit")
        first = visit("first-unchanged")
        assert first["source"] == edit["source"] != cold["source"] and "ty_project" in edit["dirty"]
        visit("traced-unchanged", "trace")
        b.consumer.write_bytes(baseline + b.BAD)
        bad = visit("warm-invalid", "ordinary", 101)
        b.consumer.write_bytes(baseline)
        visit("warm-repair", "ordinary")
        b.clear()
        ref = visit("empty-edited", "trace")
        probes(arm, env, ref)
        b.clear()
        b.consumer.write_bytes(baseline + b.BAD)
        emptybad = visit("empty-invalid", "ordinary", 101)
        b.consumer.write_bytes(baseline)
        visit("empty-repair", "ordinary")
        assert bad["errors"] == emptybad["errors"]
        diags.append(bad["errors"])
        assert len(set(images)) == 1 and len(set(libraries[:5])) == 1, (arm, images, libraries)
        summary[arm] = {
            "generator_ELF": images[0],
            "generator_rlib": libraries[0],
            "independent_generator_rlibs": sorted(set(libraries)),
            "measurements": measured,
        }
        b.clear()
    assert (
        len(set(inventories)) == len(expected) == 1
        and all(x == diags[0] for x in diags)
        and all(x == bodies[0] for x in bodies)
    )
    m.save(
        O / "conditional-images.json",
        {
            "generator_differs": summary["B"]["generator_ELF"] != summary["Q"]["generator_ELF"],
            "generator_rlib_differs": summary["B"]["generator_rlib"]
            != summary["Q"]["generator_rlib"],
        },
    )
    m.save(O / "check-verified.json", summary)
    import builds

    for pair in ("AB", "QC") if row == "01" else ("QC", "AB"):

        def role(e, index):
            return configure(e, pair[int(index)])

        builds.study(b, env, role, s.keep_elf, direction, "01" if row == "01" else "10")
        (O / "ordinary-lib").rename(O / ("linked-" + pair))
        (R / "reader-stable").rename(R / ("reader-stable-" + pair))
    from provider import check

    check(m, b.load, b.NATIVE, env, lambda e, index: configure(e, "BQ"[int(index)]), b.wild)
    assert (
        not b.wild.with_name("libutil.so").exists()
        and b.consumer.read_bytes() == baseline
        and wrapper.stat().st_ino == st.st_ino
        and wrapper.stat().st_ctime_ns == st.st_ctime_ns
    )
    b.edited(False)
    m.save(
        O / "complete.json",
        {
            "row": row,
            "arm_order": sequence,
            "sources": bodies[0],
            "invalid_repair": True,
            "actual_wrapper": m.sha(wrapper),
            "conditional": "B vs Q only ever use fresh isolated roots",
        },
    )
    print("qualified", row, sequence, flush=True)


if __name__ == "__main__":
    main()
