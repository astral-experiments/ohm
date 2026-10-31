"""Read the two original failed panels without treating the source-built link roster as admitted."""

from pathlib import Path
import gzip, json, os, sys

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import reopen as a
import signed_readers as h
import formats as f


def links(bs, root, tools):
    get = lambda n: a.J(bs[n])
    found = {}
    for phase in ("traced-repeat", "independent-empty"):
        prefix = root + "/" + phase + "/"
        v = get(prefix + "build.json")
        comp = []
        ld = []
        rows = bs[prefix + "kernel/exec.tsv"].decode().splitlines()
        for ix, line in enumerate(rows, 1):
            n, p, d, i, match, image = line.split("\t")
            assert int(n) == ix and not int(match)
            body = bs[prefix + f"kernel/args-{ix:04d}"]
            assert body.endswith(b"\0")
            args = [os.fsdecode(x) for x in body[:-1].split(b"\0")]
            ident = [int(d), int(i)]
            if (
                ident == tools["rustc"]["dev_ino"]
                and "--crate-name" in args
                and "--out-dir" in args
                and not any(t.startswith("--print") for t in args)
            ):
                name = args[args.index("--crate-name") + 1]
                assert not any(t in ("link-only", "-Zlink-only") for t in args)
                comp.append(
                    {"pid": int(p), "crate": name, "image": image, "argv": args}
                )
            if ident == tools["wild"]["dev_ino"] and "-o" in args:
                ld.append([int(p), args[args.index("-o") + 1]])
        assert (
            [[p["pid"], p["crate"]] for p in comp] == v["physical_rustcs"]
            and ld == v["wild"]
            and len(ld) == 1
        )
        if phase == "traced-repeat":
            assert [p["crate"] for p in comp] == [
                "build_script_build",
                "unicode_names2",
            ]
            assert "-Zohm-shared-stages" in comp[1]["argv"] and any(
                x.startswith("incremental=") for x in comp[1]["argv"]
            )
            assert ld[0][1] == v["physical_generator"][0][1]
        else:
            assert (
                len(comp) == 17
                and len([c for c in comp if c["crate"] == "unicode_names2_generator"])
                == 1
            )
        found[phase] = {"rustc": comp, "wild": ld}
    return found


def primary(bs, row, desc):
    get = lambda n: a.J(bs[n])
    reg = get("actual-compiler-enrollment.json")
    sub = get("initial-acquisition-subjects.json")
    assert (
        reg["head"] == a.HEAD
        and int(reg["run"]) == a.RUN
        and reg["sequence"] == a.ORDER[row]
        and reg["direction"] == a.DIR[row]
    )
    assert (
        reg["check"] == a.CMD
        and reg["configs"] == a.CFG
        and reg["seal"] == get("compiler-source-seal.json") == a.SEAL
        and reg["plan"] == h.sha((a.D.parent / "PLAN.md").read_bytes())
    )
    assert (
        h.SOURCES == sub["source"] == reg["source"]
        and h.PATCH == reg["history"] == sub["history"]
    )
    assert (
        not (a.KEYS & reg["environment"].keys())
        and len(get("host.json")["actual"]) == 8
        and len(get("initial-acquisition-strict.json")["locked"]) == 498
    )
    assert all(
        k not in bs
        for k in (
            "all-selections.json",
            "complete.json",
            "same-profile-decision.json",
            "native-provider/verified.json",
        )
    )
    placements = sorted(
        [
            k.split("/")[0]
            for k in bs
            if k.startswith("selection-") and k.endswith("/selection.json")
        ],
        key=lambda k: int(k.split("-")[1]),
    )
    selection = []
    for i, base in enumerate(placements):
        s = get(base + "/selection.json")
        assert base == f"selection-{i}-{s['role']}"
        selection.append(
            {
                "role": s["role"],
                "version": s["version"],
                "tools": s["tools"],
                "record": base,
            }
        )
    # The aggregate index was deliberately never committed on this unsuccessful run.
    # The individual placement records still each have the physical OS open and immutable manifest.
    closure = lambda n: selection if n == "all-selections.json" else get(n)
    roles, sdk = a.products(bs, closure, sub, reg)
    cal = f.calibration(bs)
    graphs = {}
    options = {}
    subject = {}
    warnings = set()
    errs = []
    good = set()
    held = {}
    first = (sub["original_blob"], sub["historical_parent_blob"])
    first = first if row == "01" else first[::-1]
    for arm in a.ORDER[row]:
        root = "opt" + arm
        r, lv = arm
        t = roles[r]
        rt = get(root + "/runtime.json")
        assert rt["tools"] == t and rt in selection
        graphs[arm] = f.unit_profiles(
            a.J(gzip.decompress(bs[root + "/unit-graph.json.gz"]))
        )
        phase = {}
        images = set()
        for name in (*a.SCORE, *a.TRACE, *a.ORD):
            phase[name] = a.check_visit(
                bs,
                root + "/" + name,
                name,
                arm,
                first,
                options,
                t,
                good,
                warnings,
                errs,
                images,
            )
        assert len(images) == 1
        held[arm] = images.pop()
        effective = get(root + "/checks.json")
        assert (
            effective["stdout"] == "true true true\n"
            and f.codegen(effective["actual_scope"]) == (lv, "on", "on")
            and not any("share-generics" in x for x in effective["actual_scope"])
        )
        drv = a.driver_proof(bs, root, reg, t, r)
        lookup = get(root + "/actual-cargo-driver/verified.json")
        assert lookup["sha256"] == a.SHA[r]
        defined, imported = [
            gzip.decompress(bs[root + "/library-symbols-" + s + ".gz"])
            for s in ("defined", "imported")
        ]
        subject[arm] = {
            "visits": phase,
            "driver": {"sha": lookup["sha256"], "pids": drv},
            "neutral_symbols": {
                "defined_rows": len(defined.splitlines()),
                "import_rows": len(imported.splitlines()),
                "defined_sha": h.sha(defined),
                "import_sha": h.sha(imported),
            },
        }
    assert (
        len(good) == len(warnings) == 1
        and len(errs) == 12
        and all(e == errs[0] for e in errs)
    )
    assert held == get("check-verified.json")["neutral_elf"]
    for lv in "012":
        l, r = graphs["P" + lv], graphs["C" + lv]
        assert l == r
        for x, y in zip(options["P" + lv], options["C" + lv]):
            assert x.keys() == y.keys() and all(
                sorted(x[k], key=repr) == sorted(y[k], key=repr) for k in x
            )
    for role in "PC":
        base = graphs[role + "0"]
        for lv in "12":
            new = graphs[role + lv]
            assert base.keys() == new.keys()
            (k,) = [k for k in base if base[k] != new[k]]
            assert (
                "ruff_unicode_names2_generator" in k
                and len(base[k]) == len(new[k]) == 1
                and base[k][0] | {"opt_level": lv} == new[k][0]
            )
    metrics = {}
    for lv in "012":
        metrics[lv] = {}
        for endpoint in (*a.SCORE, "edit_plus_repeat"):
            legs = (
                ("historical-edit", "first-unchanged")
                if endpoint == "edit_plus_repeat"
                else (endpoint,)
            )
            money = {}
            for role in "PC":
                v = subject[role + lv]["visits"]
                money[role] = {
                    "native_user_instructions": sum(v[x]["instructions"] for x in legs),
                    "allocated_B": v[legs[-1]]["allocated_B"],
                }
            money["P_over_C"] = (
                money["P"]["native_user_instructions"]
                / money["C"]["native_user_instructions"]
            )
            money["C_minus_P_allocated_B"] = (
                money["C"]["allocated_B"] - money["P"]["allocated_B"]
            )
            metrics[lv][endpoint] = money
    scoped = "0" if row == "01" else "2"
    link_report = {}
    assert [
        k for k in bs if k.startswith("linked-opt") and k.endswith("/input.json")
    ] == ["linked-opt" + scoped + "/input.json"]
    for i, role in enumerate("PC"):
        root = "linked-opt" + scoped + "/opt" + str(i)
        r = f.linked(bs, "opt" + scoped, role + scoped, i)
        raw = links(bs, root, roles[role])
        observed = {}
        for phase in r:
            s = get(root + "/" + phase + "/build.json")
            typed = [
                a.J(x)
                for x in gzip.decompress(
                    bs[root + "/" + phase + "/stdout.gz"]
                ).splitlines()
            ]
            (u,) = [
                u
                for u in typed
                if u["reason"] == "compiler-artifact"
                and u["target"]["name"] == "unicode_names2"
                and u["target"]["kind"] == ["lib"]
            ]
            assert s["rlib"][0] in u["filenames"] and not u["fresh"]
            observed[phase] = {
                "method": s["mode"],
                "target_rlib_sha256_recorded": s["rlib"][1],
                "reader_sha256": s["reader_elf"]["sha256"],
                "reader": s["reader"],
                "returned_rlib": s["rlib"][0],
                "Cargo_dirty": s["dirty"],
                "generated": s["generated"],
                "generator": s["generator"]["sha256"],
                "profile": u["profile"],
            }
            if phase in raw:
                observed[phase]["physical"] = raw[phase]
        assert (
            len({v["reader_sha256"] for v in observed.values()}) == 1
            and len(
                {json.dumps(v["generated"], sort_keys=True) for v in observed.values()}
            )
            == 1
        )
        assert (
            observed["first-unchanged"]["target_rlib_sha256_recorded"]
            != observed["independent-empty"]["target_rlib_sha256_recorded"]
        )
        link_report[role] = {"visits": r, "observed": observed}
    assert (
        link_report["P"]["observed"]["first-unchanged"]["reader_sha256"]
        == link_report["C"]["observed"]["first-unchanged"]["reader_sha256"]
    )
    return {
        "enrollment": {
            "row": row,
            "head": reg["head"],
            "run": reg["run"],
            "host": reg["host"],
            "sequence": reg["sequence"],
            "direction": reg["direction"],
            "sdk": sdk,
            "seal": reg["seal"],
            "actual_selects": placements,
        },
        "raw_zip": desc,
        "raw_members": len(bs),
        "native_calibrations": len(cal) * 4,
        "check_subjects": subject,
        "check_graph_units": 338,
        "check_healthy_artifact_count": 303,
        "check_error": "E0308",
        "check_fresh_ratios": metrics,
        "working_generator_elf": held,
        "linked_level": scoped,
        "linked_unadmitted": link_report,
        "missing_panels": [
            "linked O1 at both workers",
            "all 36 provider visits",
            "full registered comparison decision",
        ],
    }


def main(root):
    result = []
    for row in ("01", "02"):
        name = root / ("actual-compiler-loop-" + row)
        desc = a.J(name.with_suffix(".json").read_bytes())
        bs = a.opened(name.with_suffix(".zip").read_bytes(), desc, row)
        result.append(primary(bs, row, desc))
        del bs
    assert result[0]["enrollment"]["host"] != result[1]["enrollment"]["host"]
    return {
        "run": a.RUN,
        "head": a.HEAD,
        "official_both_jobs": "failure",
        "complete_qualifying_pairs": 0,
        "workers": result,
        "status": "Incomplete registered study. Completed primary measures and out-of-scope link rosters are diagnostic only.",
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path, nargs="?", default=D)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    result = main(args.directory)
    data = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.write_text(data)
    else:
        print(data, end="")
