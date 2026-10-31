"""Run the two ordinary profile-rustflags acquisitions on exact signed tools and private outputs."""

from collections import defaultdict
from pathlib import Path
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "strict-share-bridge"))
import bridge as ancestor

s, b, m = ancestor.s, ancestor.b, ancestor.m
R, S, O = m.R, m.S, m.O
row = os.environ["QA_ROW"]
order = {"01": "ABQC", "02": "CQBA"}[row]
direction = {"01": "reverse", "02": "forward"}[row]
level = ancestor.upper
FLAG = "-Zshare-generics=no"
SOURCE = ancestor.generator_source
common = "[unstable]\nprofile-rustflags = true\n"
section = "\n[profile.dev.package.ruff_unicode_names2_generator]\n"
configs = {
    k: (
        common
        + (section + f"opt-level = {v}\n" if v else "")
        + (f'rustflags = ["{FLAG}"]\n' if k == "Q" else "")
    ).encode()
    for k, v in level.items()
}
forbidden = {
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "OHM_BRIDGE_ARM",
    "RUSTFLAGS",
    "CARGO_ENCODED_RUSTFLAGS",
    "CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL",
    "CI",
    "TF_BUILD",
}
prior = json.loads((HERE / "prior.json").read_bytes())["observed"]


def select(env, arm):
    p = Path(env["CARGO_HOME"]) / "config.toml"
    assert (
        p.parent == S / "cargo-home" and not (p.parent / "config").exists() and not p.is_symlink()
    )
    assert not (forbidden & env.keys())
    current = p.read_bytes() if p.exists() else None
    assert current is None or current in configs.values()
    if current != configs[arm]:
        tmp = p.with_name("unwrapped-profile-incoming")
        assert not tmp.exists()
        tmp.write_bytes(configs[arm])
        tmp.replace(p)
    assert p.read_bytes() == configs[arm]
    return env


def trace(where, arm, roster=None):
    rid = b.rust.stat()
    wid = b.wild.stat()
    history = defaultdict(list)
    stages = []
    allc = []
    named = []
    wild = []
    for pid, ident, _, image, a in m.argv(where / "kernel"):
        assert "bridge-workspace-rustc" not in image
        full = (
            "--crate-name" in a and "--out-dir" in a and not any(x.startswith("--print") for x in a)
        )
        if ident == [rid.st_dev, rid.st_ino] and full:
            assert not history[pid], (pid, history[pid], image)
            crate = a[a.index("--crate-name") + 1]
            src = next((v for v in a if v.endswith(".rs") and not v.startswith("-")), None)
            flag = [v for v in a if "share-generics" in v]
            selected = crate == "unicode_names2_generator" and SOURCE == src
            assert flag == ([FLAG] if selected and arm == "Q" else []), (where, crate, flag)
            if selected:
                opt = b.argspec(a)
                assert opt["opt"] == str(level[arm]) and opt["debug"] == opt["overflow"] == "on"
                assert (
                    "--emit=dep-info,metadata,link" in a
                    and "--target" not in a
                    and "-Zohm-shared-stages" in a
                )
                named.append([pid, a])
            if "-Zohm-shared-stages" in a:
                assert src
                stages.append(
                    src.split("/registry/src/", 1)[-1] if "/registry/src/" in src else src
                )
            allc.append([pid, crate])
        if ident == [wid.st_dev, wid.st_ino] and "-o" in a:
            wild.append([pid, a[a.index("-o") + 1]])
        history[pid].append(image)
    out = {
        "actual_full": len(allc),
        "stage_sources": sorted(stages),
        "workspace": sum(s.startswith("crates/") for s in stages),
    }
    if roster:
        assert out == prior[roster], (where, arm, roster, len(allc), len(stages), out["workspace"])
        assert len(wild) == (48 if roster == "check-cold" else 1)
        assert len(named) == int(roster.endswith("-cold"))
    m.save(
        where / "ordinary-physical.json",
        {
            "role": arm,
            "roster": roster,
            "stages": out,
            "direct_rustcs": allc,
            "wild": wild,
            "generator_compiler": named,
        },
    )
    return out


def hash_graphs(d):
    base = S / "target" / "debug" / "incremental"
    assert base.is_dir() and not base.is_symlink()
    files = []
    for n in ("ohm-check-dep-graph.bin", "query-cache.bin"):
        for p in sorted(base.rglob(n)):
            assert p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(base)
            st = p.stat()
            with p.open("rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            after = p.stat()
            assert (st.st_dev, st.st_ino, st.st_size, st.st_ctime_ns, st.st_mtime_ns) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_ctime_ns,
                after.st_mtime_ns,
            )
            files.append(
                [
                    str(p.relative_to(S)),
                    st.st_dev,
                    st.st_ino,
                    st.st_size,
                    st.st_blocks * 512,
                    st.st_mtime_ns,
                    st.st_ctime_ns,
                    digest,
                ]
            )
    assert any(
        "ty_python_semantic" in x[0] and x[0].endswith("/query-cache.bin") for x in files
    ) and any(
        "ty_python_semantic" in x[0] and x[0].endswith("/ohm-check-dep-graph.bin") for x in files
    )
    m.save(d / "graph-contents.json", files)


def migrations(arm):
    if arm == "A":
        return ["Q", "A"]
    if (row, arm) == ("01", "B"):
        return ["Q", "B"]
    if (row, arm) == ("02", "Q"):
        return ["B", "Q"]
    return []


def main():
    env = b.procure()
    assert not (forbidden & env.keys()) and not (Path(env["CARGO_HOME"]) / "config.toml").exists()
    m.save(
        O / "profile-enrollment.json",
        {
            "head": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
            "row": row,
            "order": order,
            "source_direction": direction,
            "configs": {k: v.decode() for k, v in configs.items()},
            "plan": m.sha(HERE / "PLAN.md"),
            "prior": m.sha(HERE / "prior.json"),
            "host": os.uname().nodename,
        },
    )
    original = b.consumer.read_bytes()
    assert original == m.w.git(m.src, "show", "HEAD:crates/ty_project/src/lib.rs")
    common_gen = None
    good = set()
    warnings = set()
    errors = []
    graph = {}
    held = {}
    artifacts = defaultdict(set)
    before = direction == "forward"
    for arm in order:
        b.clear()
        b.edited(before)
        select(env, arm)
        graph[arm] = s.graph(env, arm)
        where = O / ("opt" + arm)

        def visit(label, mode="score", desired=arm, rc=0, flank=None):
            nonlocal common_gen
            select(env, desired)
            r = b.visit(arm, label, env, mode, rc)
            gen, lib = ancestor.retained(where / label, desired)
            artifacts[desired].add(gen)
            m.save(
                where / label / "profile-state.json",
                {
                    "mode": desired,
                    "settings_sha": m.h(configs[desired]),
                    "neutral_elf": gen,
                    "host_rlib": lib,
                    "target": str(S / "target"),
                    "shared": str(S / "shared"),
                },
            )
            if rc:
                errors.extend(r["errors"])
            else:
                assert r["typed"] == 303 and not r["errors"]
                good.add(r["logical_sha"])
                warnings.add(tuple(r["warning_sha"]))
            if common_gen is None:
                common_gen = r["generated"]
            assert common_gen == r["generated"]
            if mode == "trace":
                s.kernel(where / label, desired, label)
                trace(where / label, desired, flank)
            return r

        cold = visit("cold")
        visit("neutral-unchanged")
        b.edited(not before)
        edit = visit("historical-edit")
        rep = visit("first-unchanged")
        assert cold["source"] != rep["source"] == edit["source"] and "ty_project" in edit["dirty"]
        visit("traced-unchanged", "trace", flank="check-repeat")
        dests = migrations(arm)
        if dests:
            hash_graphs(where / "first-unchanged")
        for i, dest in enumerate(dests, 1):
            for suffix in ("change", "unchanged"):
                n = f"move-{i}-{suffix}"
                visit(n, desired=dest)
                hash_graphs(where / n)
        b.clear()
        ref = visit("empty-edited", "trace", flank="check-cold")
        held[arm] = m.read(where / "empty-edited" / "neutral-generator.json")["sha256"]
        ancestor.probes(arm, env, ref)
        b.consumer.write_bytes(original + b.BAD)
        bad = visit("warm-invalid", "ordinary", rc=101)
        b.consumer.write_bytes(original)
        visit("warm-repair", "ordinary")
        for i, dest in enumerate(dests, 1):
            visit(f"move-{i}-physical", "trace", desired=dest)
            visit(f"move-{i}-settled-physical", "trace", desired=dest, flank="check-repeat")
        b.clear()
        b.consumer.write_bytes(original + b.BAD)
        failed = visit("empty-invalid", "ordinary", rc=101)
        b.consumer.write_bytes(original)
        visit("empty-repair", "ordinary")
        assert failed["errors"] == bad["errors"]
        b.clear()
    assert (
        len(good) == len(warnings) == 1 and len(errors) == 8 and all(e == errors[0] for e in errors)
    )
    assert (
        held["A"] == "9d9a0837b0233fda1e4abd51dcfc4e3c2c3a4ab01b41ad6fc460adc1b2f5dc1a"
        and held["B"] == "a10dcb362a57bda3888794fd69f87d1174407fedc37de6dd0db178266f8d7d9a"
    ), held
    for arm in order:
        assert artifacts[arm] == {held[arm]}, (arm, artifacts[arm], held[arm])
    roles = graph["A"].keys()
    assert all(g.keys() == roles for g in graph.values())
    diff = {}
    for x, y in ("AB", "BQ", "QC", "AC"):
        changes = {k: [graph[x][k], graph[y][k]] for k in roles if graph[x][k] != graph[y][k]}
        assert len(changes) == 1 and all("ruff_unicode_names2_generator" in k for k in changes)
        ((lhs, rhs),) = changes.values()
        assert len(lhs) == len(rhs) == 1
        for v, k in ((lhs[0], x), (rhs[0], y)):
            assert (
                v["opt_level"] == str(level[k])
                and v.get("rustflags", []) == ([FLAG] if k == "Q" else [])
                and v["debug_assertions"]
                and v["overflow_checks"]
            )
        assert {k: v for k, v in lhs[0].items() if k not in ("opt_level", "rustflags")} == {
            k: v for k, v in rhs[0].items() if k not in ("opt_level", "rustflags")
        }
        diff[x + y] = changes
    m.save(
        O / "check-verified.json",
        {
            "role_graph_fields": diff,
            "neutral_ELFs": held,
            "generated": common_gen,
            "typed": 303,
            "source_and_failed_repairs": True,
        },
    )
    import builds

    for pair in ("AB", "QC") if row == "01" else ("QC", "AB"):
        builds.study(
            b,
            env,
            lambda e, index: select(e, pair[int(index)]),
            s.keep_elf,
            direction,
            "01" if row == "01" else "10",
        )
        dest = O / ("linked-" + pair)
        (O / "ordinary-lib").rename(dest)
        (R / "reader-stable").rename(R / ("reader-stable-" + pair))
        for index, case in enumerate(pair):
            for lab, which in (
                ("traced-repeat", "build-repeat"),
                ("independent-empty", "build-cold"),
            ):
                trace(dest / ("opt" + str(index)) / lab, case, which)
    from provider import check

    check(m, b.load, b.NATIVE, env, lambda e, i: select(e, "BQ"[int(i)]), b.wild)
    assert not b.wild.with_name("libutil.so").exists() and b.consumer.read_bytes() == original
    select(env, "A")
    b.edited(False)
    m.save(
        O / "complete.json",
        {
            "row": row,
            "order": order,
            "sources": common_gen,
            "migrations": {k: migrations(k) for k in order},
            "qualified": True,
        },
    )
    print("qualified unwrapped", row, order, flush=True)


if __name__ == "__main__":
    main()
