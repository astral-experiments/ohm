"""Reopen the two original native runs without a toolchain or any network access."""

from collections import defaultdict
from pathlib import Path
import ast
import gzip
import io
import json
import os
import re
import statistics
import sys
import zipfile

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import formats as f
import signed_readers as h

J = h.read
HEAD = "dc3af5609ca8a38c77d81892ccf594dead476621"
RUN = 41157269898
OPT = {"A": 0, "B": 1, "Q": 1, "C": 2}
ORDER = {"01": "ABQC", "02": "CQBA"}
FLAG = "-Zshare-generics=no"
GEN = "crates/ruff_unicode_names2_generator/src/lib.rs"
PRIOR = J((D.parent / "prior.json").read_bytes())["observed"]
SCORE = ("cold", "neutral-unchanged", "historical-edit", "first-unchanged")
CHANGES = {"01": {"A": ("Q", "A"), "B": ("Q", "B")}, "02": {"A": ("Q", "A"), "Q": ("B", "Q")}}


def opened(raw, meta, row):
    assert meta["workflow_run"]["id"] == RUN and meta["workflow_run"]["head_sha"] == HEAD
    assert (
        meta["name"] == "unwrapped-profile-" + row
        and meta["size_in_bytes"] == len(raw)
        and meta["digest"] == "sha256:" + h.sha(raw)
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None and z.namelist() == [meta["name"] + ".tar.gz"]
        return h.unpack(z.read(z.namelist()[0]))


def profiles(arm):
    doc = "[unstable]\nprofile-rustflags = true\n"
    if arm != "A":
        doc += f"\n[profile.dev.package.ruff_unicode_names2_generator]\nopt-level = {OPT[arm]}\n"
    if arm == "Q":
        doc += 'rustflags = ["-Zshare-generics=no"]\n'
    return doc


def actual_switches(a):
    opts = []
    for i, t in enumerate(a):
        if t in ("-C", "-Z"):
            group, arg = t, a[i + 1]
        elif len(t) > 2 and t[:2] in ("-C", "-Z"):
            group, arg = t[:2], t[2:]
        else:
            continue
        key, eq, v = arg.partition("=")
        if group == "-C" and key in ("metadata", "extra-filename"):
            pattern = "[0-9a-f]{16}" if key == "metadata" else "-[0-9a-f]{16}"
            assert re.fullmatch(pattern, v), (t, arg)
            v = "<Cargo artifact identity>"
        if group == "-C" and key == "incremental":
            assert Path(v).is_absolute() and "incremental" in Path(v).parts
            v = "<Cargo incremental output directory>"
        opts.append(group + key + (eq + v if eq else ""))
    return opts


def native(bs, path, tools, arm, roster):
    rid = tools["rustc"]["dev_ino"]
    wid = tools["wild"]["dev_ino"]
    history = defaultdict(list)
    stages = []
    compiles = []
    links = []
    selected = []
    levels = defaultdict(list)
    switches = defaultdict(list)
    for line in bs[path + "/kernel/exec.tsv"].decode().splitlines():
        idx, pid, dev, ino, _, exe = line.split("\t")
        pid = int(pid)
        ident = [int(dev), int(ino)]
        raw = bs[path + "/kernel/args-" + idx.zfill(4)]
        assert raw.endswith(b"\0")
        a = [os.fsdecode(x) for x in raw[:-1].split(b"\0")]
        assert "bridge-workspace-rustc" not in exe
        if (
            ident == rid
            and "--crate-name" in a
            and "--out-dir" in a
            and not any(x.startswith("--print") for x in a)
        ):
            assert not history[pid]
            crate = a[a.index("--crate-name") + 1]
            source = next((n for n in a if n.endswith(".rs") and not n.startswith("-")), None)
            gen = source == GEN and crate == "unicode_names2_generator"
            flag = [x for x in a if "share-generics" in x]
            assert flag == ([FLAG] if gen and arm == "Q" else [])
            if gen:
                assert (
                    f.codegen(a) == (str(OPT[arm]), "on", "on")
                    and "--emit=dep-info,metadata,link" in a
                    and "--target" not in a
                    and "-Zohm-shared-stages" in a
                )
                selected.append([pid, a])
            if "-Zohm-shared-stages" in a:
                assert source
                stages.append(
                    source.split("/registry/src/", 1)[-1] if "/registry/src/" in source else source
                )
            assert not any(x in ("link-only", "-Zlink-only") for x in a)
            compiles.append([pid, crate])
            levels[f.physical_role(a)].append([*f.codegen(a), bool(flag)])
            switches[f.physical_role(a)].append(actual_switches(a))
        if ident == wid and "-o" in a:
            links.append([pid, a[a.index("-o") + 1]])
        history[pid].append(exe)
    observed = {
        "actual_full": len(compiles),
        "stage_sources": sorted(stages),
        "workspace": sum(x.startswith("crates/") for x in stages),
    }
    original = J(bs[path + "/ordinary-physical.json"])
    assert original == {
        "role": arm,
        "roster": roster,
        "stages": observed,
        "direct_rustcs": compiles,
        "wild": links,
        "generator_compiler": selected,
    }
    if roster:
        assert (
            observed == PRIOR[roster]
            and len(selected) == int(roster.endswith("-cold"))
            and len(links) == (48 if roster == "check-cold" else 1)
        )
    return (
        {
            "full": len(compiles),
            "wild": len(links),
            "workspace_shared_stage": observed["workspace"],
            "all_shared_stage": len(stages),
            "compiled_names": sorted(c[1] for c in compiles) if len(compiles) < 50 else None,
            "selected_signed_compilers": selected,
        },
        dict(levels),
        dict(switches),
    )


def graph_contents(bs, base, led):
    table = {r[0]: r for r in led}
    originals = J(bs[base + "/graph-contents.json"])
    included = {
        k: v
        for k, v in table.items()
        if k.startswith("target/debug/incremental/")
        and Path(k).name in ("ohm-check-dep-graph.bin", "query-cache.bin")
    }
    names = {r[0] for r in originals}
    before_only = set(included) - names
    sampled_only = names - set(included)
    assert len(included) == len(originals)
    if before_only or sampled_only:
        assert base.endswith("/first-unchanged")
        shape = lambda path: (Path(path).parts[-3], Path(path).name)
        before_roles = sorted(shape(path) for path in before_only)
        sampled_roles = sorted(shape(path) for path in sampled_only)
        assert before_roles == sampled_roles and len(sampled_roles) == len(set(sampled_roles))
        possible = {
            ("build_script_build", "query-cache.bin"),
            ("unicode_names2", "query-cache.bin"),
            ("unicode_names2", "ohm-check-dep-graph.bin"),
        }
        assert all((crate.rsplit("-", 1)[0], name) in possible for crate, name in sampled_roles)
    else:
        assert not before_only and not sampled_only
    rows = []
    for path, dev, ino, sz, allocated, mtime, ctime, digest in originals:
        assert re.fullmatch("[0-9a-f]{64}", digest)
        if path in included:
            old = included[path]
            assert [dev, ino, sz, allocated] == [old[1], old[2], old[5], old[4] * 512]
        rows.append([path, dev, ino, sz, allocated, digest])
    return rows, {
        "paths_matching_paid_ledger": len(names) - len(sampled_only),
        "paid_paths_superseded_by_unscored_repeat": sorted(before_only),
        "new_paths_sampled_immediately_before_switch": sorted(sampled_only),
    }


def growth(initial, new):
    before = {(r[1], r[2]): r for r in initial}
    after = {(r[1], r[2]): r for r in new}

    def scope(path):
        p = Path(path)
        package, suffix = p.parts[-3].rsplit("-", 1)
        assert re.fullmatch("[a-z0-9]+", suffix)
        return package, p.name

    oldhashes = {(scope(r[0]), r[5]) for r in initial}
    groups = defaultdict(lambda: defaultdict(int))
    semantic = []
    for key, r in after.items():
        if key in before:
            relation = (
                "same_inode_same_content"
                if r[5] == before[key][5]
                else "same_inode_changed_content"
            )
        else:
            relation = (
                "new_inode_matching_original_hash"
                if (scope(r[0]), r[5]) in oldhashes
                else "new_inode_distinct_hash"
            )
        n = Path(r[0]).name
        groups[n][relation] += r[4]
        if "ty_python_semantic" in r[0] and (key not in before or r[5] != before[key][5]):
            semantic.append([r[0], r[4], r[5], relation])
    return {
        "current_blocks_by_file_and_identity": dict(groups),
        "ty_python_semantic_changed_rows": semantic,
        "ty_python_semantic_originals": [
            [r[0], r[3], r[4], r[5]]
            for r in before.values()
            if scope(r[0])[0] == "ty_python_semantic"
        ],
    }


def provider_args(bs):
    out = {}
    for i, arm in enumerate("BQ"):
        notes = {}
        for lab in ("held-83", "held-47", "malformed", "remove"):
            d = f"native-provider/opt{i}/empty/{lab}"
            rows = gzip.decompress(bs[d + "/exec-and-provider-open.gz"]).decode().splitlines()
            found = []
            for line in rows:
                if GEN not in line:
                    continue
                mt = re.match(r'^\S+ (\d+) execve\("([^"]+)", (\[.*\]), .*\)\s+= 0$', line)
                if not mt:
                    continue
                a = ast.literal_eval(mt[3])
                if (
                    Path(mt[2]).name != "rustc"
                    or "--crate-name" not in a
                    or a[a.index("--crate-name") + 1] != "unicode_names2_generator"
                ):
                    continue
                assert (
                    f.codegen(a) == ("1", "on", "on")
                    and [x for x in a if "share-generics" in x] == ([FLAG] if arm == "Q" else [])
                    and "-Zohm-shared-stages" in a
                )
                found.append(int(mt[1]))
            assert len(found) == 1
            notes[lab] = found[0]
        out[arm] = notes
    return out


def audit(bs, row, meta):
    get = lambda name: J(bs[name])
    reg = get("profile-enrollment.json")
    sub = get("subjects.json")
    sig = get("strict.json")
    complete = get("complete.json")
    assert (
        reg["head"] == sig["head"] == HEAD
        and reg["row"] == complete["row"] == row
        and int(reg["run"]) == RUN
    )
    assert (
        reg["order"] == complete["order"] == ORDER[row]
        and reg["plan"] == h.sha((D.parent / "PLAN.md").read_bytes())
        and reg["prior"] == h.sha((D.parent / "prior.json").read_bytes())
    )
    assert (
        reg["configs"] == {v: profiles(v) for v in OPT}
        and complete["qualified"]
        and complete["migrations"] == {a: list(CHANGES[row].get(a, ())) for a in ORDER[row]}
    )
    assert (
        h.CARGO in sig["selected"]
        and sig["cargo"] == h.FIXED
        and len(sig["locked"]) == 498
        and len(get("host.json")["actual"]) == 8
    )
    built = get("strict-cargo-artifact.json")["build"]
    assert built["compiled"] == built["delivered"] == h.FIXED and built["candidate"] == h.CARGO
    assert (
        sub["source"] == h.SOURCES
        and sub["history"] == h.PATCH
        and sig["signed"]["rustc"]
        == "f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9"
        and sig["signed"]["wild"]
        == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
    )
    excluded = {
        "CI",
        "TF_BUILD",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTC_WRAPPER",
        "CARGO_ENCODED_RUSTFLAGS",
        "RUSTFLAGS",
        "OHM_BRIDGE_ARM",
        "CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL",
    }
    assert not (excluded & sig["environment"].keys())
    cal = f.calibration(bs)
    profilesets = {}
    compilerflags = {}
    options = {}
    outputs = defaultdict(set)
    allerr = []
    good = set()
    warn = set()
    genfiles = None
    arms = {}
    reference = get("check-verified.json")
    original, edited = (
        (sub["original_blob"], sub["historical_parent_blob"])
        if row == "01"
        else (sub["historical_parent_blob"], sub["original_blob"])
    )
    for arm in ORDER[row]:
        root = "opt" + arm
        doc = J(gzip.decompress(bs[root + "/unit-graph.json.gz"]))
        profilesets[arm] = f.unit_profiles(doc)
        legs = CHANGES[row].get(arm, ())
        visits = {}
        hashes = {}
        phases = (
            [(n, arm, "score", None) for n in SCORE]
            + [
                ("traced-unchanged", arm, "trace", "check-repeat"),
                ("empty-edited", arm, "trace", "check-cold"),
            ]
            + [
                (n, arm, "ordinary", None)
                for n in ("warm-invalid", "warm-repair", "empty-invalid", "empty-repair")
            ]
        )
        for num, dest in enumerate(legs, 1):
            phases += [
                (f"move-{num}-{suffix}", dest, "score", None) for suffix in ("change", "unchanged")
            ]
            phases += [
                (f"move-{num}-physical", dest, "trace", None),
                (f"move-{num}-settled-physical", dest, "trace", "check-repeat"),
            ]
        for name, desired, mode, roster in phases:
            path = root + "/" + name
            v = get(path + "/visit.json")
            state = get(path + "/profile-state.json")
            assert state["mode"] == desired and state["settings_sha"] == h.sha(
                profiles(desired).encode()
            )
            rc = 101 if name.endswith("invalid") else 0
            assert (
                v["source"] == (original if name in ("cold", "neutral-unchanged") else edited)
                and v["phase"] == name
                and v["arm"] == arm
                and v["exit"] == rc
            )
            typed = [J(l) for l in gzip.decompress(bs[path + "/stdout.gz"]).splitlines()]
            assert typed[-1] == {"reason": "build-finished", "success": not rc}
            cargo = [u for u in typed if u["reason"] == "compiler-artifact"]
            errors = [u["message"] for u in typed if u.get("message", {}).get("level") == "error"]
            assert (
                len(cargo) == v["typed"]
                and v["dirty"] == [u["target"]["name"] for u in cargo if not u["fresh"]]
                and not any(x["executable"] for x in cargo)
            )
            logical = sorted(
                set(
                    json.dumps(
                        [
                            u["package_id"],
                            u["target"]["name"],
                            u["target"]["kind"],
                            u["features"],
                            u["profile"]["test"],
                        ],
                        separators=(",", ":"),
                    )
                    for u in cargo
                )
            )
            body = json.dumps(logical, separators=(",", ":")).encode()
            assert (
                gzip.decompress(bs[path + "/logical.gz"]) == body
                and h.sha(body) == v["logical_sha"]
                and v["errors"] == errors
            )
            if rc:
                (error,) = errors
                assert error["code"]["code"] == "E0308" and any(
                    s["is_primary"]
                    and s["file_name"] == "crates/ty_project/src/lib.rs"
                    and "OHM_HOST_PROFILE_BAD_TYPE" in "".join(x["text"] for x in s["text"])
                    for s in error["spans"]
                )
                allerr.append(error)
            else:
                assert len(cargo) == 303 and not errors
                good.add(v["logical_sha"])
                warn.add(tuple(v["warning_sha"]))
            prog, lib = f.source_images(bs, path, set())
            assert state["neutral_elf"] == prog["sha256"] and state["host_rlib"] == lib["sha256"]
            assert (
                len(
                    [
                        u
                        for u in cargo
                        if u["target"]["name"] == "unicode_names2_generator"
                        and lib["path"] in u["filenames"]
                        and u["profile"] == lib["cargo_profile"]
                    ]
                )
                == 1
            )
            assert (
                len(
                    [
                        u
                        for u in cargo
                        if u["target"]["kind"] == ["custom-build"]
                        and "/crates/ruff_unicode_names2#" in u["package_id"]
                        and prog["path"] in u["filenames"]
                    ]
                )
                == 1
            )
            outputs[desired].add(prog["sha256"])
            if genfiles is None:
                genfiles = v["generated"]
            assert (
                v["generated"] == genfiles == complete["sources"]
                and all(
                    h.sha(gzip.decompress(bs["generated/" + v + ".gz"])) == v
                    for v in genfiles.values()
                )
                and sorted(genfiles) == ["generated.rs", "generated_alias.rs", "generated_phf.rs"]
            )
            rec = {
                "mode": desired,
                "typed": len(cargo),
                "dirty": len(v["dirty"]),
                "neutral_elf": prog["sha256"],
                "generator_rlib": lib["sha256"],
            }
            if mode == "score":
                rec["instructions"] = h.hw(get(path + "/whole.json"))
                rec["allocated_B"] = h.disk(bs, path, v["storage"])
                led = J(gzip.decompress(bs[path + "/allocated-ledger.gz"]))
                rec["regions_B"] = f.region(led)
                assert (
                    sum(rec["regions_B"].values()) == rec["allocated_B"]
                    and v["instructions"] == rec["instructions"]
                )
                if legs and (name == "first-unchanged" or name.startswith("move-")):
                    hashes[name], rec["hash_snapshot_timing"] = graph_contents(bs, path, led)
            if mode == "trace":
                rec["physical"], flags, switches = native(bs, path, sub["tools"], desired, roster)
                if name == "empty-edited":
                    compilerflags[arm] = flags
                    options[arm] = switches
                base = h.trace(bs, path, sub["tools"], v)
                assert (
                    base["full"] == rec["physical"]["full"]
                    and base["link_only"] == 0
                    and base["wild"] == rec["physical"]["wild"]
                )
            visits[name] = rec
        if legs:
            for i, _ in enumerate(legs, 1):
                for suffix in ("change", "unchanged"):
                    name = f"move-{i}-{suffix}"
                    visits[name]["cache_change_vs_first_unchanged"] = growth(
                        hashes["first-unchanged"], hashes[name]
                    )
        call = get(root + "/effective-settings.json")
        assert (
            call["stdout"] == "true true true\n"
            and f.codegen(call["actual_scope"]) == (str(OPT[arm]), "on", "on")
            and [s for s in call["supplied_argv"] if "share-generics" in s]
            == ([FLAG] if arm == "Q" else [])
        )
        pair = "AB" if arm in "AB" else "QC"
        ordinal = pair.index(arm)
        secondary = f.linked(bs, pair, arm, ordinal)
        for n, g in (("traced-repeat", "build-repeat"), ("independent-empty", "build-cold")):
            proof, _, _ = native(bs, f"linked-{pair}/opt{ordinal}/{n}", sub["tools"], arm, g)
            secondary[n]["physical"] = proof
        arms[arm] = {"check": visits, "build": secondary}
    assert len(allerr) == 8 and all(e == allerr[0] for e in allerr) and len(good) == len(warn) == 1
    held = {k: next(iter(v)) for k, v in outputs.items() if len(v) == 1}
    assert (
        len(held) == 4 and held == reference["neutral_ELFs"] and genfiles == reference["generated"]
    )
    assert (
        held["A"] == "9d9a0837b0233fda1e4abd51dcfc4e3c2c3a4ab01b41ad6fc460adc1b2f5dc1a"
        and held["B"] == "a10dcb362a57bda3888794fd69f87d1174407fedc37de6dd0db178266f8d7d9a"
    )
    diffs = {}
    for kind, observations, match in (
        ("graph", profilesets, "ruff_unicode_names2_generator"),
        ("physical", compilerflags, GEN),
    ):
        diffs[kind] = {}
        for x, y in ("AB", "BQ", "QC", "AC"):
            l, r = observations[x], observations[y]
            assert l.keys() == r.keys()
            change = {
                k: [l[k], r[k]] for k in l if sorted(l[k], key=repr) != sorted(r[k], key=repr)
            }
            assert len(change) == 1 and all(match in k for k in change)
            lhs, rhs = next(iter(change.values()))
            if kind == "physical":
                assert [lhs, rhs] == [
                    [[str(OPT[x]), "on", "on", x == "Q"]],
                    [[str(OPT[y]), "on", "on", y == "Q"]],
                ]
            else:
                assert change == reference["role_graph_fields"][x + y] and len(lhs) == len(rhs) == 1
                for a, p in ((x, lhs[0]), (y, rhs[0])):
                    assert p["opt_level"] == str(OPT[a]) and p.get("rustflags", []) == (
                        [FLAG] if a == "Q" else []
                    )
                project = lambda v: {
                    k: r for k, r in v.items() if k not in ("opt_level", "rustflags")
                }
                assert project(lhs[0]) == project(rhs[0])
            diffs[kind][x + y] = change
    diffs["complete_-C_-Z_switches"] = {}
    for lhs, rhs in ("AB", "BQ", "QC", "AC"):
        left, right = options[lhs], options[rhs]
        assert left.keys() == right.keys()
        changed = {k: [left[k], right[k]] for k in left if sorted(left[k]) != sorted(right[k])}
        if (lhs, rhs) == ("B", "Q"):
            assert len(changed) == 1 and GEN in next(iter(changed))
            lopt, ropt = next(iter(changed.values()))
            assert len(lopt) == len(ropt) == 1 and [s for s in ropt[0] if s != FLAG] == lopt[0]
        diffs["complete_-C_-Z_switches"][lhs + rhs] = changed
    provider = h.providers(bs, get)
    assert provider["runs"] == 18
    physical_providers = provider_args(bs)
    ratios = {}
    for kind in ("check", "build"):
        edit = "historical-edit" if kind == "check" else "historical-hunk"
        out = {}
        for n in ("cold", "neutral-unchanged", edit, "first-unchanged", "edit_plus_repeat"):
            stages = (edit, "first-unchanged") if n == "edit_plus_repeat" else (n,)
            count = {t: sum(arms[t][kind][m]["instructions"] for m in stages) for t in ORDER[row]}
            out[n] = {p: count[p[0]] / count[p[1]] for p in ("BQ", "AQ", "AC", "CQ", "AB")}
        ratios[kind] = out
    budgets = {}
    for arm, legs in CHANGES[row].items():
        vs = arms[arm]["check"]
        initial = vs["first-unchanged"]["allocated_B"]
        for i, nextmode in enumerate(legs, 1):
            current = vs[f"move-{i}-unchanged"]["allocated_B"]
            budgets[arm + str(i)] = {
                "initial_profile": arm,
                "active": nextmode,
                "initial_bytes": initial,
                "settled_bytes": current,
                "delta_B": current - initial,
                "growth_fraction": (current - initial) / initial,
                "within_10pct_and_80MiB": current <= 1.1 * initial
                and current - initial <= 80 * 2**20,
            }
    B = arms["B"]["check"]
    Q = arms["Q"]["check"]
    cost = Q["cold"]["instructions"] / B["cold"]["instructions"]
    delta = Q["first-unchanged"]["allocated_B"] - B["first-unchanged"]["allocated_B"]
    return {
        "row": row,
        "order": ORDER[row],
        "host": reg["host"],
        "source_dir": reg["source_direction"],
        "archive": meta,
        "members": len(bs),
        "calibrations": len(cal) * 4,
        "neutral_ELFs": held,
        "generated": genfiles,
        "diffs": diffs,
        "arms": arms,
        "ratios": ratios,
        "migration_gates": budgets,
        "provider_signed_pids": physical_providers,
        "provider_native": provider,
        "fresh_gates": {
            "B/Q_above_one": ratios["check"]["first-unchanged"]["BQ"] > 1,
            "A/Q_at_least_two": ratios["check"]["first-unchanged"]["AQ"] >= 2,
            "Q_over_B_cold": cost,
            "cold_budget_pass": cost <= 1.05,
            "Q_minus_B_disk": delta,
            "fresh_disk_budget_pass": delta <= 8 * 2**20
            and delta <= 0.01 * B["first-unchanged"]["allocated_B"],
        },
    }


def main(source):
    results = []
    for row in ORDER:
        p = source / ("unwrapped-profile-" + row)
        meta = J(p.with_suffix(".json").read_bytes())
        bs = opened(p.with_suffix(".zip").read_bytes(), meta, row)
        results.append(audit(bs, row, meta))
    assert (
        results[0]["host"] != results[1]["host"]
        and results[0]["neutral_ELFs"] == results[1]["neutral_ELFs"]
        and results[0]["generated"] == results[1]["generated"]
    )
    return {
        "head": HEAD,
        "run": RUN,
        "source": h.SOURCES,
        "cargo": h.CARGO,
        "rustc": "c79998a5cd143c445a4b2528f20953b176a65c5d",
        "workers": results,
    }


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]) if len(sys.argv) > 1 else D), indent=2, sort_keys=True))
