"""Offline whole-cohort reopener. Original artifacts, exact physical tool identities, no compilation."""

from pathlib import Path
import argparse, collections, gzip, hashlib, io, json, math, re, statistics, sys, zipfile

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import broad_reader as h

HEAD = "3c9c82bb960564dbe3b0df7c0a736662354e502d"
RUN = 41154300915
REG = json.loads((D.parent / "order.json").read_bytes())
P = "ruff_unicode_names2_generator"
SCORE = [
    "cold",
    "neutral-unchanged",
    "historical-edit",
    "first-unchanged",
    "switch-profile",
    "switch-unchanged",
]
FLANK = ["empty-edited", "traced-unchanged", "switch-physical"]
PLAIN = ["warm-invalid", "warm-repair", "empty-invalid", "empty-repair"]
NATIVE = h.CARGO


def facts(bs, base, tools, rec):
    existing = h.trace(bs, base, tools, rec)
    reg = h.read(bs[base + "/all-physical.json"])
    rows = []
    wild = []
    physical_generators = []
    rust = tools["rustc"]["dev_ino"]
    ld = tools["wild"]["dev_ino"]
    seen = {}
    for l in bs[base + "/kernel/exec.tsv"].decode().splitlines():
        i, p, d, n, selected, image = l.split("\t")
        pid = int(p)
        ident = [int(d), int(n)]
        argv = [v.decode() for v in bs[base + f"/kernel/args-{int(i):04d}"][:-1].split(b"\0")]
        if ident == ld and "-o" in argv:
            wild.append([pid, argv[argv.index("-o") + 1]])
        if "ruff_unicode_names2" in image and Path(image).name in (
            "build-script-build",
            "build_script_build",
        ):
            physical_generators.append([pid, image])
        if (
            ident != rust
            or "--crate-name" not in argv
            or "--out-dir" not in argv
            or any(t.startswith("--print") for t in argv)
        ):
            continue
        crate = argv[argv.index("--crate-name") + 1]
        source = next((t for t in argv if t.endswith(".rs") and not t.startswith("-")), None)
        emit = next(t for t in argv if t.startswith("--emit="))
        features = sorted(
            argv[j + 1]
            for j, t in enumerate(argv)
            if t == "--cfg" and argv[j + 1].startswith("feature=")
        )
        mode = "link-only" if any(t in ("-Zlink-only", "link-only") for t in argv) else "full"
        opt = {}
        for j, t in enumerate(argv):
            if t == "-C":
                val = argv[j + 1]
            elif t.startswith("-C") and len(t) > 2:
                val = t[2:]
            else:
                continue
            k, _, v = val.partition("=")
            opt[k] = v
        if source is None:
            assert (
                re.fullmatch("autocfg_[0-9a-f]{16}_0", crate)
                and "/memoffset/" in argv[argv.index("--out-dir") + 1]
                and "-" in argv
                and emit == "--emit=llvm-ir"
            )
            source = "<exclusive memoffset autocfg stdin probe>"
        level = opt.get("opt-level", "0")
        debug = opt.get("debug-assertions", "on" if level == "0" else "off")
        overflow = opt.get("overflow-checks", debug)
        rows.append([crate, source, emit, features, mode, level, debug, overflow, pid])
        logical = (
            "autocfg_<memoffset-stdin>_0"
            if source == "<exclusive memoffset autocfg stdin probe>"
            else crate
        )
        k = json.dumps([logical, source, emit, features, mode], separators=(",", ":"))
        seen.setdefault(k, []).append([level, debug, overflow])
    assert (
        rows == reg["compilers"]
        and wild == reg["links"]
        and physical_generators == reg["generators"]
    )
    assert existing["full"] + existing["link_only"] == len(rows)
    existing["compiler_names"] = sorted(x[0] for x in rows)
    existing["destinations"] = sorted(x[1] for x in wild)
    proven = collections.Counter()
    for crate, source, emit, flags, mode, level, debug, overflow, pid in rows:
        names = re.findall(r"(?:^crates/|/registry/src/[^/]+/)([^/]+)/", source)
        package = (
            names[0]
            if len(names) == 1
            else (
                "memoffset::autocfg"
                if source == "<exclusive memoffset autocfg stdin probe>"
                else source
            )
        )
        proven[(package, crate if not source.startswith("<") else "autocfg_stdin", mode)] += 1
    existing["physical_units"] = [[*q, count] for q, count in sorted(proven.items())]
    return existing, {k: sorted(v) for k, v in seen.items()}


def full_graph(bs, key):
    doc = h.read(gzip.decompress(bs[key + "/unit-graph.json.gz"]))
    out = {}
    for u in doc["units"]:
        k = json.dumps(
            [
                u["pkg_id"],
                u["target"]["name"],
                u["target"]["kind"],
                u["mode"],
                u["features"],
                u.get("platform"),
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        out.setdefault(k, []).append(u["profile"])
    return {k: sorted(v, key=lambda q: json.dumps(q, sort_keys=True)) for k, v in out.items()}


def check_elf(bs, desc, keep):
    data = gzip.decompress(bs["retained-ELF/" + desc["sha256"] + ".gz"])
    assert (
        h.sha(data) == desc["sha256"]
        and data[:6] == b"\x7fELF\x02\x01"
        and data[18:20] == b">\x00"
        and len(data) == desc["bytes"]
    )
    keep.add(desc["sha256"])
    return desc["sha256"]


def secondary(bs, keep):
    base = "ordinary-lib/"
    doc = h.read(bs[base + "input.json"])
    assert (
        doc["hunk"] == "bfedc614b7670b8766576b64afd426c292f8c2ce"
        and doc["base"] == "9e66456a0167e332cd50175f529708362c2fa2ce1f5c17daf34d3b87c2e46669"
    )
    assert doc["argv"] == [
        "cargo",
        "+ohm",
        "build",
        "-p",
        "ruff_unicode_names2",
        "--lib",
        "--locked",
        "--offline",
        "-j4",
        "--message-format=json",
    ]
    assert b"let num_escapes = (lexicon_words.len() + 255) / 256;" in gzip.decompress(
        bs[base + "public-commit-diff.gz"]
    )
    result = {}
    body = None
    for arm in ("0", "1"):
        local = {}
        r_elf = {}
        for label in (
            "cold",
            "neutral-unchanged",
            "historical-hunk",
            "first-unchanged",
            "traced-repeat",
            "independent-empty",
        ):
            path = base + "opt" + arm + "/" + label
            v = h.read(bs[path + "/build.json"])
            assert (
                v["label"] == label
                and v["role"] == arm
                and v["source"] in (doc["base"], doc["reverse"])
            )
            assert v["reader"] == "Some(0)\nSome(0)\nSome(65)\nSome(9731)\n"
            r_elf[label] = check_elf(bs, v["reader_elf"], keep)
            gen = check_elf(bs, v["generator"], keep)
            msgs = [h.read(l) for l in gzip.decompress(bs[path + "/stdout.gz"]).splitlines()]
            assert msgs[-1] == {"reason": "build-finished", "success": True} and not any(
                x.get("message", {}).get("level") == "error" for x in msgs
            )
            (ar,) = [
                r
                for r in msgs
                if r.get("target", {}).get("name") == "unicode_names2"
                and r["target"]["kind"] == ["lib"]
            ]
            assert v["rlib"][0] in ar["filenames"]
            assert (
                len(
                    [
                        r
                        for r in msgs
                        if r["reason"] == "build-script-executed"
                        and r["package_id"] == ar["package_id"]
                    ]
                )
                == 1
            )
            assert v["dirty"] == [
                r["target"]["name"]
                for r in msgs
                if r["reason"] == "compiler-artifact" and not r["fresh"]
            ]
            if body is None:
                body = v["generated"]
            assert v["generated"] == body and all(
                h.sha(gzip.decompress(bs["generated/" + digest + ".gz"])) == digest
                for digest in body.values()
            )
            if v["mode"] == "score":
                local[label] = {
                    "instructions": h.hw(h.read(bs[path + "/whole.json"])),
                    "allocated_B": h.disk(bs, path, v["storage"]),
                    "dirty": v["dirty"],
                    "generator_ELF": gen,
                }
            else:
                assert (
                    v["wild"]
                    and len(v["physical_generator"]) == 1
                    and any(x[1] == v["physical_generator"][0][1] for x in v["wild"])
                )
                local[label] = {
                    "physical_rustcs": v["physical_rustcs"],
                    "real_wilds": len(v["wild"]),
                    "generator_ELF": gen,
                }
        assert r_elf["first-unchanged"] == r_elf["independent-empty"]
        assert "unicode_names2_generator" in local["historical-hunk"]["dirty"]
        result[arm] = local
    return {
        "arms": result,
        "ratio": {
            label: result["0"][label]["instructions"] / result["1"][label]["instructions"]
            for label in ("cold", "neutral-unchanged", "historical-hunk", "first-unchanged")
        },
    }


def audit(bs, row, meta):
    meta_h = h.read(bs["strict.json"])
    sub = h.read(bs["subjects.json"])
    job = h.read(bs["single.json"])
    assert (
        meta["workflow_run"]["id"] == RUN
        and meta["workflow_run"]["head_sha"] == meta_h["head"] == job["commit"] == HEAD
    )
    assert (
        job["row"] == row
        and [job["order"], job["source_direction"]] == REG[row]
        and job["orders"] == REG
        and int(job["run"]) == RUN
        and meta_h["host"] == job["host"]
    )
    assert job["override"] == "[profile.dev.package.ruff_unicode_names2_generator]\nopt-level = 1\n"
    assert (
        meta_h["cargo"] == h.FIXED
        and NATIVE in meta_h["selected"]
        and len(meta_h["locked"]) == 498
        and sub["source"] == h.SOURCES
        and sub["history"] == h.PATCH
        and job["plan"] == h.sha((D.parent / "PLAN.md").read_bytes())
    )
    assert sub["original_blob"] != sub["historical_parent_blob"]
    assert (
        len(h.read(bs["host.json"])["actual"]) == 8
        and not {
            "CI",
            "TF_BUILD",
            "RUSTFLAGS",
            "RUSTC_WRAPPER",
            "RUSTC_WORKSPACE_WRAPPER",
            "CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL",
        }
        & meta_h["environment"].keys()
    )
    cargo = h.read(bs["strict-cargo-artifact.json"])
    assert (
        cargo["build"]["compiled"] == cargo["build"]["delivered"] == h.FIXED
        and cargo["build"]["candidate"] == NATIVE
    )
    assert (
        sub["tools"]["rustc"]["sha256"]
        == "f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9"
        and sub["tools"]["wild"]["sha256"]
        == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
    )
    calibration = []
    for i, (mode, n) in enumerate(
        (("0", 1), ("1", 1), ("2", 1), ("2", 2), ("exec", 1), ("thread", 1), ("thread", 2))
    ):
        val = [h.hw(h.read(bs[f"calibration/{i}-{j}.json"])) for j in range(4)]
        d = statistics.median(val[1::2]) - statistics.median(val[::2])
        expected = 160_000_000 * n
        assert abs(d / expected - 1) < 0.02
        calibration.append([mode, n, val, d, expected])
    assert calibration == h.read(bs["calibration/verified.json"])
    states = h.read(bs["delta.json"])
    terminal = h.read(bs["complete.json"])
    assert terminal == {
        "row": row,
        "order": job["order"],
        "direction": job["source_direction"],
        "qualified": True,
    }
    source0, source1 = (
        (sub["historical_parent_blob"], sub["original_blob"])
        if job["source_direction"] == "forward"
        else (sub["original_blob"], sub["historical_parent_blob"])
    )
    groups = {}
    roles = {}
    kept = set()
    allerr = []
    unique_bodies = set()
    logical = set()
    warnings = set()
    graphs = {}
    for arm in job["order"]:
        d = "opt" + arm
        graphs[arm] = full_graph(bs, d)
        same = set()
        summary = {}
        for name in [*SCORE, *FLANK, *PLAIN]:
            base = d + "/" + name
            r = h.read(bs[base + "/visit.json"])
            failed = name.endswith("invalid")
            assert (
                r["arm"] == arm
                and r["phase"] == name
                and r["source"] == (source0 if name in ("cold", "neutral-unchanged") else source1)
            )
            assert r["exit"] == (101 if failed else 0)
            msgs = [h.read(l) for l in gzip.decompress(bs[base + "/stdout.gz"]).splitlines()]
            assert msgs[-1] == {"reason": "build-finished", "success": not failed}
            units = [v for v in msgs if v["reason"] == "compiler-artifact"]
            assert r["typed"] == len(units) and r["dirty"] == [
                u["target"]["name"] for u in units if not u["fresh"]
            ]
            errs = [x["message"] for x in msgs if x.get("message", {}).get("level") == "error"]
            assert errs == r["errors"] and len(errs) == int(failed)
            abi = sorted(
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
                    for u in units
                )
            )
            encoded = json.dumps(abi, separators=(",", ":")).encode()
            assert (
                gzip.decompress(bs[base + "/logical.gz"]) == encoded
                and h.sha(encoded) == r["logical_sha"]
                and not any(u["executable"] for u in units)
            )
            if failed:
                assert errs[0]["code"]["code"] == "E0308" and any(
                    s["is_primary"]
                    and s["file_name"] == "crates/ty_project/src/lib.rs"
                    and "OHM_HOST_PROFILE_BAD_TYPE" in "".join(k["text"] for k in s["text"])
                    for s in errs[0]["spans"]
                )
                allerr.extend(errs)
            else:
                logical.add(r["logical_sha"])
                warnings.add(tuple(r["warning_sha"]))
            assert sorted(r["generated"]) == [
                "generated.rs",
                "generated_alias.rs",
                "generated_phf.rs",
            ] and all(
                h.sha(gzip.decompress(bs["generated/" + dig + ".gz"])) == dig
                for dig in r["generated"].values()
            )
            unique_bodies.add(tuple(sorted(r["generated"].items())))
            gen = h.read(bs[base + "/neutral-generator.json"])
            actual = check_elf(bs, gen, kept)
            assert (
                len(
                    [
                        u
                        for u in units
                        if gen["path"] in u["filenames"]
                        and u["target"]["kind"] == ["custom-build"]
                        and "/crates/ruff_unicode_names2#" in u["package_id"]
                    ]
                )
                == 1
            )
            effective = ("1" if arm == "0" else "0") if name.startswith("switch-") else arm
            if effective == arm and not failed:
                same.add(actual)
            if name in SCORE:
                v = {
                    "instructions": h.hw(h.read(bs[base + "/whole.json"])),
                    "allocated_B": h.disk(bs, base, r["storage"]),
                    "typed": r["typed"],
                    "dirty_count": len(r["dirty"]),
                }
                assert states["states"][arm][name] == [
                    v["instructions"],
                    v["allocated_B"],
                    v["dirty_count"],
                ]
                summary[name] = v
            if name in FLANK:
                physical, allgroups = facts(bs, base, sub["tools"], r)
                assert physical["roles"].get("unicode_build_script", []) in ([], ["0"])
                if name == "empty-edited":
                    groups[arm] = allgroups
                    assert physical["roles"] == {
                        "phf_generator": ["0"],
                        "unicode_build_script": ["0"],
                        "unicode_names2_generator": [arm],
                        "unicode_names2": ["1"],
                        "ty_project": ["1"],
                    }
                # Keep full compiler names for actual migration and unchanged. All raw args/destinations remain in the packet.
                if name == "empty-edited":
                    physical.pop("compiler_names")
                    physical.pop("physical_units")
                physical.pop("destinations")
                summary[name] = physical
        assert len(same) == 1 and states["neutral_ELFs"][arm] == next(iter(same))
        assert all(
            q["ran"] == "true true true\n" for q in h.read(bs[d + "/flag-probes.json"]).values()
        )
        roles[arm] = {
            "visits": summary,
            "neutral_ELF": next(iter(same)),
            "graph_units": sum(len(v) for v in graphs[arm].values()),
        }
    assert (
        len(logical) == len(warnings) == len(unique_bodies) == 1
        and len(allerr) == 4
        and all(err == allerr[0] for err in allerr)
    )
    assert groups["0"].keys() == groups["1"].keys() and graphs["0"].keys() == graphs["1"].keys()
    graphdelta = {
        k: [graphs["0"][k], graphs["1"][k]] for k in graphs["0"] if graphs["0"][k] != graphs["1"][k]
    }
    argdelta = {
        k: [groups["0"][k], groups["1"][k]] for k in groups["0"] if groups["0"][k] != groups["1"][k]
    }
    assert (
        states["graph"] == graphdelta
        and states["compilers"] == argdelta
        and len(graphdelta) == len(argdelta) == 1
        and all(P in key for key in [*graphdelta, *argdelta])
    )
    assert list(argdelta.values()) == [[[["0", "on", "on"]], [["1", "on", "on"]]]]
    secondary_result = secondary(bs, kept) if row in ("01", "02") else None
    providers = h.providers(bs, lambda k: h.read(bs[k])) if row in ("01", "02") else None
    return {
        "row": row,
        "order": job["order"],
        "source_direction": job["source_direction"],
        "host": job["host"],
        "calibrated_native_commands": 28,
        "archive_id": meta["id"],
        "archive_sha256": meta["digest"][7:],
        "archive_bytes": meta["size_in_bytes"],
        "members": len(bs),
        "neutral_sources": dict(next(iter(unique_bodies))),
        "arms": roles,
        "secondary_build": secondary_result,
        "provider_commands": providers["runs"] if providers else 0,
        "retained_ELFs": sorted(kept),
    }


def aggregate(rows):
    assert (
        len(rows) == 12
        and {x["row"] for x in rows} == set(REG)
        and len({x["host"] for x in rows})
        == len({x["archive_id"] for x in rows})
        == len({x["archive_sha256"] for x in rows})
        == 12
        and collections.Counter((x["order"], x["source_direction"]) for x in rows)
        == {(o, d): 3 for o in ("01", "10") for d in ("forward", "reverse")}
    )
    assert (
        sum(x["provider_commands"] for x in rows) == 36
        and sum(x["calibrated_native_commands"] for x in rows) == 336
        and len({tuple(sorted(x["neutral_sources"].items())) for x in rows}) == 1
    )

    def ci(x):
        vals = sorted(x)
        assert len(vals) == 12
        return {
            "median": statistics.median(vals),
            "interval": [vals[2], vals[9]],
            "minimum": vals[0],
            "maximum": vals[-1],
        }

    def ins(r, a, n):
        return r["arms"][a]["visits"][n]["instructions"]

    def disk(r, a, n):
        return r["arms"][a]["visits"][n]["allocated_B"]

    ratios = {
        n: ci([ins(r, "0", n) / ins(r, "1", n) for r in rows])
        for n in ("cold", "neutral-unchanged", "historical-edit", "first-unchanged")
    }
    ratios["edit_plus_first_unchanged"] = ci(
        [
            (ins(r, "0", "historical-edit") + ins(r, "0", "first-unchanged"))
            / (ins(r, "1", "historical-edit") + ins(r, "1", "first-unchanged"))
            for r in rows
        ]
    )
    primary = ratios["first-unchanged"]
    dirs = {
        d: statistics.median(
            ins(r, "0", "first-unchanged") / ins(r, "1", "first-unchanged")
            for r in rows
            if r["source_direction"] == d
        )
        for d in ("forward", "reverse")
    }
    cold = ci([ins(r, "1", "cold") / ins(r, "0", "cold") for r in rows])
    fresh = [(disk(r, "0", "first-unchanged"), disk(r, "1", "first-unchanged")) for r in rows]
    mixed = [
        (
            disk(r, "0", "first-unchanged"),
            max(disk(r, a, n) for a in ("0", "1") for n in ("switch-profile", "switch-unchanged")),
        )
        for r in rows
    ]
    resources = {}
    for label, vals in [("fresh", fresh), ("mixed", mixed)]:
        resources[label] = {
            "added_B": ci([(b - a) for a, b in vals]),
            "ratio": ci([b / a for a, b in vals]),
        }
    budgets = {
        "primary_lower_ge_2": primary["interval"][0] >= 2 and all(v >= 2 for v in dirs.values()),
        "cold_upper_le_1.05": cold["interval"][-1] <= 1.05,
        "fresh_upper_within_8MiB_and_1pct": resources["fresh"]["added_B"]["interval"][-1]
        <= 8 * (1 << 20)
        and resources["fresh"]["ratio"]["interval"][-1] <= 1.01,
        "mixed_upper_within_80MiB_and_10pct": resources["mixed"]["added_B"]["interval"][-1]
        <= 80 * (1 << 20)
        and resources["mixed"]["ratio"]["interval"][-1] <= 1.1,
    }
    phases = {
        a: {
            n: {
                "user_instructions": ci([ins(r, a, n) for r in rows]),
                "allocated_B": ci([disk(r, a, n) for r in rows]),
                "dirty_artifacts": sorted({r["arms"][a]["visits"][n]["dirty_count"] for r in rows}),
            }
            for n in SCORE
        }
        for a in ("0", "1")
    }
    return {
        "source": h.SOURCES,
        "historical_edit": h.PATCH,
        "compiler": CARGO_HEAD,
        "commands": {
            "counted_primary": len(rows) * 2 * len(SCORE),
            "ordinary_secondary_signed_hosts": 2,
            "provider_commands": 36,
            "calibrations": 336,
        },
        "registered_head": HEAD,
        "run": RUN,
        "pair_count": 12,
        "sign_interval_coverage": 1 - 2 * sum(math.comb(12, x) for x in range(3)) / 4096,
        "gates": budgets,
        "direction_medians": dirs,
        "comparison_default_over_optimized": ratios,
        "cold_optimized_over_default": cold,
        "resources": resources,
        "phases": phases,
        "pairs": sorted(rows, key=lambda v: v["row"]),
    }


CARGO_HEAD = h.CARGO


def open_archive(raw, metadata, row):
    assert (
        metadata["name"] == "one-package-" + row
        and metadata["digest"] == "sha256:" + h.sha(raw)
        and metadata["size_in_bytes"] == len(raw)
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.namelist() == ["one-package-" + row + ".tar.gz"] and z.testzip() is None
        return h.unpack(z.read(z.namelist()[0]))


def run(d):
    receipts = []
    for row in sorted(REG):
        stem = "one-package-" + row
        desc = h.read((d / (stem + ".json")).read_bytes())
        msgs = open_archive((d / (stem + ".zip")).read_bytes(), desc, row)
        receipts.append(audit(msgs, row, desc))
    return aggregate(receipts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=D)
    args = parser.parse_args()
    print(json.dumps(run(args.directory), indent=2, sort_keys=True))
