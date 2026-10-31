"""Independently authenticate the compiler handoff, signed native outputs and four fresh-root measurements."""

from collections import defaultdict
import gzip, hashlib, io, json, os, re, statistics, sys, zipfile
from pathlib import Path

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import signed_readers as h

HEAD = "85ca09ee1e65e67c8123e7562f4e3ab09a35f534"
RUN = 41156082521
CASES = {"01": "ABQC", "02": "CQBA"}
OPTS = {"A": "0", "B": "1", "Q": "1", "C": "2"}
FLAG = "-Zshare-generics=no"
NAMED = "crates/ruff_unicode_names2_generator/src/lib.rs"
SCORE = ["cold", "neutral-unchanged", "historical-edit", "first-unchanged"]
TRACE = ["empty-edited", "traced-unchanged"]
RAW = ["warm-invalid", "warm-repair", "empty-invalid", "empty-repair"]
J = h.read


def open_archive(raw, desc, row):
    assert (
        desc["workflow_run"]["id"] == RUN
        and desc["workflow_run"]["head_sha"] == HEAD
        and desc["name"] == "share-bridge-" + row
        and desc["size_in_bytes"] == len(raw)
        and desc["digest"] == "sha256:" + h.sha(raw)
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None and z.namelist() == ["share-bridge-" + row + ".tar.gz"]
        return h.unpack(z.read(z.namelist()[0]))


def calibration(blobs):
    rows = []
    for k, (mode, rep) in enumerate(
        (("0", 1), ("1", 1), ("2", 1), ("2", 2), ("exec", 1), ("thread", 1), ("thread", 2))
    ):
        counts = [h.hw(J(blobs[f"calibration/{k}-{j}.json"])) for j in range(4)]
        delta = statistics.median(counts[1::2]) - statistics.median(counts[::2])
        needle = 160_000_000 * rep
        assert abs(delta / needle - 1) < 0.02
        rows.append([mode, rep, counts, delta, needle])
    assert rows == J(blobs["calibration/verified.json"])
    return rows


def codegen(args):
    d = {}
    for i, t in enumerate(args):
        if t == "-C":
            v = args[i + 1]
        elif t.startswith("-C") and len(t) > 2:
            v = t[2:]
        else:
            continue
        k, _, val = v.partition("=")
        d[k] = val
    name = d.get("opt-level", "0")
    debug = d.get("debug-assertions", "on" if name == "0" else "off")
    return name, debug, d.get("overflow-checks", debug)


def unit_profiles(doc):
    profiles = defaultdict(list)
    for u in doc["units"]:
        role = [
            u["pkg_id"],
            u["target"]["name"],
            u["target"]["kind"],
            u["mode"],
            u["features"],
            u.get("platform"),
        ]
        profiles[json.dumps(role, separators=(",", ":"))].append(u["profile"])
    assert len(doc["units"]) == 338 and all(0 <= i < 338 for i in doc["roots"])
    return {k: sorted(v, key=lambda p: json.dumps(p, sort_keys=True)) for k, v in profiles.items()}


def physical_role(a):
    crate = a[a.index("--crate-name") + 1]
    source = next((t for t in a if t.endswith(".rs") and not t.startswith("-")), None)
    emit = next(t for t in a if t.startswith("--emit="))
    if source is None:
        assert (
            re.fullmatch("autocfg_[0-9a-f]{16}_0", crate)
            and "/memoffset/" in a[a.index("--out-dir") + 1]
            and "-" in a
            and emit == "--emit=llvm-ir"
        )
        crate, source = "memoffset::autocfg", "<memoffset stdin>"
    features = sorted(
        a[j + 1] for j, t in enumerate(a) if t == "--cfg" and a[j + 1].startswith("feature=")
    )
    return json.dumps(
        [
            crate,
            source,
            emit,
            features,
            "--test" in a,
            any(x in ("-Zlink-only", "link-only") for x in a),
        ],
        separators=(",", ":"),
    )


def region(rows):
    allblocks = {}
    region = defaultdict(set)
    for name, dev, ino, mode, blocks, size, nlinks in rows:
        key = dev, ino
        assert allblocks.setdefault(key, blocks) == blocks
        parts = Path(name).parts
        location = "/".join(parts[:3]) if len(parts) >= 3 and parts[1] == "debug" else "other"
        region[key].add(location)
    allocated = defaultdict(int)
    for key, locations in region.items():
        allocated[
            next(iter(locations)) if len(locations) == 1 else "cross-area aliases, counted once"
        ] += (allblocks[key] * 512)
    return dict(allocated)


def source_images(bs, where, kept):
    root = J(bs[where + "/neutral-generator.json"])
    data = gzip.decompress(bs["retained-ELF/" + root["sha256"] + ".gz"])
    assert (
        h.sha(data) == root["sha256"]
        and data[:6] == b"\x7fELF\x02\x01"
        and data[18:20] == b">\x00"
        and len(data) == root["bytes"]
    )
    kept.add(root["sha256"])
    lib = J(bs[where + "/held-generator-rlib.json"])
    body = gzip.decompress(bs["bridge-rlibs/" + lib["sha256"] + ".gz"])
    assert h.sha(body) == lib["sha256"] and body[:8] == b"!<arch>\n" and len(body) == lib["bytes"]
    return root, lib


def handoffs(bs, d, arm, tools, wrap, seen_profiles):
    r = J(bs[d + "/visit.json"])
    raw = bs[d + "/kernel/exec.tsv"]
    r_id = tools["rustc"]["dev_ino"]
    w_id = wrap["dev_ino"]
    wi_id = tools["wild"]["dev_ino"]
    wrappers = {}
    rusts = {}
    wild = []
    generators = []
    for l in raw.decode().splitlines():
        idx, pid, dev, ino, n, image = l.split("\t")
        pid = int(pid)
        args = bs[d + f"/kernel/args-{int(idx):04d}"]
        assert args.endswith(b"\0") and n == "0"
        a = [os.fsdecode(s) for s in args[:-1].split(b"\0")]
        phys = [int(dev), int(ino)]
        if phys == w_id:
            assert pid not in wrappers and image == wrap["path"]
            wrappers[pid] = a
        if phys == r_id:
            assert pid not in rusts
            rusts[pid] = a
        if phys == wi_id and "-o" in a:
            wild.append([pid, a[a.index("-o") + 1]])
        if "ruff_unicode_names2" in image and Path(image).name in (
            "build_script_build",
            "build-script-build",
        ):
            generators.append([pid, image])
    assert wrappers and wrappers.keys() <= rusts.keys()
    targets = []
    flagged = []
    compiled = []
    wrapped = []
    physical_args = {}
    rootgen = J(bs[d + "/neutral-generator.json"])
    assert (
        len(generators) == 1
        and rootgen["path"] == generators[0][1]
        and sum(w[1] == rootgen["path"] for w in wild) == 1
    )
    for pid, a in rusts.items():
        full = (
            "--crate-name" in a and "--out-dir" in a and not any(v.startswith("--print") for v in a)
        )
        name = a[a.index("--crate-name") + 1] if "--crate-name" in a else None
        selected = name == "unicode_names2_generator" and NAMED in a
        if full:
            compiled.append([pid, name])
            if d.endswith("/empty-edited"):
                seen_profiles[physical_role(a)].append([*codegen(a), FLAG in a])
        if selected:
            assert (
                full
                and "--emit=dep-info,metadata,link" in a
                and "--target" not in a
                and pid in wrappers
                and codegen(a) == (OPTS[arm], "on", "on")
            )
            targets.append(pid)
            physical_args["generator_library_rustc"] = a
        if "crates/ruff_unicode_names2/build.rs" in a:
            assert full and codegen(a) == ("0", "on", "on") and pid in wrappers
            physical_args["build_script_rustc"] = a
        supplied = [v for v in a if "share-generics" in v]
        assert supplied == ([FLAG] if selected and arm == "Q" else [])
        if supplied:
            flagged.append(pid)
        if pid in wrappers:
            wa = wrappers[pid]
            assert (
                wa[0]
                and wa[1]
                and not any("share-generics" in v for v in wa[2:])
                and a[1:] == wa[2:] + supplied
            )
            wrapped.append([pid, len(wa) - 2, supplied])
    fresh = d.endswith("/empty-edited")
    assert len(targets) == int(fresh) and len(flagged) == int(fresh and arm == "Q")
    report = J(bs[d + "/handoff.json"])
    assert (
        sorted(report["wrapped"]) == sorted(wrapped)
        and report["selected"] == targets
        and report["flag_pids"] == flagged
        and report["actual_generator"] == generators
        and report["signed_Wilds"] == wild
    )
    baseline = h.trace(bs, d, tools, r)
    assert baseline["full"] + baseline["link_only"] == len(compiled) and baseline["wild"] == len(
        wild
    )
    assert baseline["roles"]["unicode_build_script"] == ["0"]
    if fresh:
        assert baseline["roles"] == {
            "phf_generator": ["0"],
            "ty_project": ["1"],
            "unicode_build_script": ["0"],
            "unicode_names2": ["1"],
            "unicode_names2_generator": [OPTS[arm]],
        }
    if arm == "A":
        assert (len(compiled), len(wild)) == ((304, 48) if fresh else (3, 1))
    # Every raw argument survives in the packet; keep the small selected pair directly retrievable for the cold native reader.
    return {
        "actual_full": baseline["full"],
        "link_only": baseline["link_only"],
        "wild": len(wild),
        "gens": len(generators),
        "compilers_on_repeat": None if fresh else sorted(n for p, n in compiled),
        "wrapped_invocations": len(wrappers),
        "changed_physical_rustc_argv": len(flagged),
        "selected_compiler_pids": targets,
        "workspace_generator_args": physical_args if fresh else None,
    }


def linked(bs, pair, case, which):
    base = "linked-" + pair + "/opt" + str(which) + "/"
    docs = J(bs["linked-" + pair + "/input.json"])
    assert docs["hunk"] == "bfedc614b7670b8766576b64afd426c292f8c2ce" and docs["argv"] == [
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
    results = {}
    readers = {}
    bodies = []
    for label in (
        "cold",
        "neutral-unchanged",
        "historical-hunk",
        "first-unchanged",
        "traced-repeat",
        "independent-empty",
    ):
        w = base + label
        v = J(bs[w + "/build.json"])
        rows = [J(l) for l in gzip.decompress(bs[w + "/stdout.gz"]).splitlines()]
        assert rows[-1] == {"reason": "build-finished", "success": True} and not any(
            r.get("message", {}).get("level") == "error" for r in rows
        )
        assert v["reader"] == "Some(0)\nSome(0)\nSome(65)\nSome(9731)\n"
        assert v["dirty"] == [
            r["target"]["name"]
            for r in rows
            if r["reason"] == "compiler-artifact" and not r["fresh"]
        ]
        for n, k in v["generated"].items():
            assert h.sha(gzip.decompress(bs["generated/" + k + ".gz"])) == k
        bodies.append(v["generated"])
        for elf in (v["generator"], v["reader_elf"]):
            bits = gzip.decompress(bs["retained-ELF/" + elf["sha256"] + ".gz"])
            assert bits[:6] == b"\x7fELF\x02\x01" and h.sha(bits) == elf["sha256"]
        readers[label] = v["reader_elf"]["sha256"]
        rec = {
            "source": v["source"],
            "dirty": v["dirty"],
            "generator_elf": v["generator"]["sha256"],
        }
        if v["mode"] == "score":
            rec["instructions"] = h.hw(J(bs[w + "/whole.json"]))
            rec["allocated_B"] = h.disk(bs, w, v["storage"])
            rec["regions"] = region(J(gzip.decompress(bs[w + "/allocated-ledger.gz"])))
            assert sum(rec["regions"].values()) == rec["allocated_B"]
        else:
            assert any(p[1] == v["physical_generator"][0][1] for p in v["wild"])
            rec["rustcs"] = v["physical_rustcs"]
            rec["wild"] = len(v["wild"])
        results[label] = rec
    assert (
        readers["first-unchanged"] == readers["independent-empty"]
        and all(x == bodies[0] for x in bodies)
        and results["historical-hunk"]["source"] != results["cold"]["source"]
        and "unicode_names2_generator" in results["historical-hunk"]["dirty"]
    )
    return results


def verify_other_kernel(bs, where, arm, wrap, tools, is_empty):
    rid = tools["rustc"]["dev_ino"]
    wrapid = wrap["dev_ino"]
    wrapped = {}
    rustc = {}
    matched = []
    for l in bs[where + "/kernel/exec.tsv"].decode().splitlines():
        n, p, d, i, _, exe = l.split("\t")
        pid = int(p)
        ident = [int(d), int(i)]
        argv = [os.fsdecode(x) for x in bs[where + "/kernel/args-" + n.zfill(4)][:-1].split(b"\0")]
        if ident == wrapid:
            assert exe == wrap["path"]
            wrapped[pid] = argv
        if ident == rid:
            rustc[pid] = argv
    assert wrapped and wrapped.keys() <= rustc.keys()
    for pid, a in rustc.items():
        sel = (
            "--crate-name" in a
            and a[a.index("--crate-name") + 1] == "unicode_names2_generator"
            and NAMED in a
        )
        extra = [FLAG] if arm == "Q" and sel else []
        assert [x for x in a if "share-generics" in x] == extra
        if pid in wrapped:
            assert wrapped[pid][2:] + extra == a[1:]
        if sel:
            assert pid in wrapped and codegen(a) == (OPTS[arm], "on", "on")
            matched.append(pid)
    assert len(matched) == int(is_empty)
    return {
        "workspace_wrapped": len(wrapped),
        "eligible": matched,
        "flagged_selected": int(bool(matched) and arm == "Q"),
    }


def provider_flags(bs):
    import ast

    result = {}
    for index, arm in enumerate(("B", "Q")):
        receipts = {}
        for name in ("held-83", "held-47", "malformed", "remove"):
            phase = f"native-provider/opt{index}/empty/{name}"
            raw = gzip.decompress(bs[phase + "/exec-and-provider-open.gz"])
            opts = {}
            wrapper = {}
            for line in raw.decode().splitlines():
                if (
                    "crates/ruff_unicode_names2_generator/src/lib.rs" not in line
                    or "--crate-name" not in line
                ):
                    continue
                v = re.match(r'^\S+ (\d+) execve\("([^"]+)", (\[.*\]), .*\)\s+= 0$', line)
                if not v:
                    continue
                a = ast.literal_eval(v[3])
                pid = int(v[1])
                base = Path(v[2]).name
                if base == "bridge-workspace-rustc":
                    wrapper[pid] = a
                elif base == "rustc":
                    opts[pid] = a
            assert len(opts) == 1 and set(opts) == set(wrapper)
            pid, a = next(iter(opts.items()))
            assert codegen(a) == ("1", "on", "on") and a[1:] == wrapper[pid][2:] + (
                [FLAG] if arm == "Q" else []
            )
            receipts[name] = pid
        result[arm] = receipts
    return result


def audit(bs, row, desc):
    get = lambda n: J(bs[n])
    details = get("bridge.json")
    sdk = get("subjects.json")
    root = get("strict.json")
    done = get("complete.json")
    spec = get("check-verified.json")
    assert (
        details["head"] == root["head"] == HEAD
        and int(details["run"]) == RUN
        and details["row"] == row
        and details["sequence"] == list(CASES[row])
    )
    assert done["row"] == row and done["arm_order"] == CASES[row] and done["invalid_repair"]
    assert (
        details["plan_sha"] == h.sha((D.parent / "PLAN.md").read_bytes())
        and root["cargo"] == h.FIXED
        and h.CARGO in root["selected"]
        and sdk["source"] == h.SOURCES
        and sdk["history"] == h.PATCH
        and len(root["locked"]) == 498
    )
    assert (
        root["signed"]["rustc"]
        == "f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9"
        and root["signed"]["wild"]
        == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
    )
    assert len(get("host.json")["actual"]) == 8
    sign = get("strict-cargo-artifact.json")
    assert (
        sign["build"]["compiled"] == sign["build"]["delivered"] == h.FIXED
        and sign["build"]["candidate"] == h.CARGO
    )
    wrapper = details["wrapper"]
    assert (
        h.sha(bs["forward.c"]) == h.sha((D.parent / "forward.c").read_bytes()) == wrapper["source"]
        and h.sha(gzip.decompress(bs["forward-ELF.gz"]))
        == wrapper["sha256"]
        == done["actual_wrapper"]
    )
    assert (
        details["environment"]["RUSTC_WORKSPACE_WRAPPER"] == wrapper["path"]
        and not {
            "RUSTC_WRAPPER",
            "RUSTFLAGS",
            "CI",
            "TF_BUILD",
            "CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL",
        }
        & details["environment"].keys()
    )
    cal = calibration(bs)
    kept = set()
    errors = []
    inventory = set()
    warnings = set()
    generated = None
    allarms = {}
    graphs = {}
    cold_profiles = {}
    source_a, source_b = (
        (sdk["original_blob"], sdk["historical_parent_blob"])
        if row == "01"
        else (sdk["historical_parent_blob"], sdk["original_blob"])
    )
    for arm in CASES[row]:
        d = "opt" + arm
        visits = {}
        shared_elf = set()
        primary_libs = set()
        all_libs = set()
        graph = J(gzip.decompress(bs[d + "/unit-graph.json.gz"]))
        graphs[arm] = unit_profiles(graph)
        cold_profiles[arm] = defaultdict(list)
        (g,) = [u for u in graph["units"] if u["target"]["name"] == "unicode_names2_generator"]
        assert (
            g["mode"] == "build"
            and g["profile"]["opt_level"] == OPTS[arm]
            and g["profile"]["debug_assertions"]
            and g["profile"]["overflow_checks"]
        )
        for name in [*SCORE, *TRACE, *RAW]:
            p = d + "/" + name
            r = get(p + "/visit.json")
            fail = name.endswith("invalid")
            assert (
                r["arm"] == arm
                and r["phase"] == name
                and r["exit"] == (101 if fail else 0)
                and r["source"] == (source_a if name in ("cold", "neutral-unchanged") else source_b)
            )
            messages = [J(l) for l in gzip.decompress(bs[p + "/stdout.gz"]).splitlines()]
            assert messages[-1] == {"reason": "build-finished", "success": not fail}
            units = [x for x in messages if x["reason"] == "compiler-artifact"]
            errs = [x["message"] for x in messages if x.get("message", {}).get("level") == "error"]
            assert (
                errs == r["errors"]
                and len(errs) == int(fail)
                and len(units) == r["typed"]
                and not any(u["executable"] for u in units)
            )
            if fail:
                assert errs[0]["code"]["code"] == "E0308" and any(
                    s["is_primary"]
                    and s["file_name"] == "crates/ty_project/src/lib.rs"
                    and "OHM_HOST_PROFILE_BAD_TYPE" in "".join(x["text"] for x in s["text"])
                    for s in errs[0]["spans"]
                )
                errors.extend(errs)
            else:
                inventory.add(r["logical_sha"])
                warnings.add(tuple(r["warning_sha"]))
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
                    for u in units
                )
            )
            raw = json.dumps(logical, separators=(",", ":")).encode()
            assert h.sha(raw) == r["logical_sha"] and gzip.decompress(bs[p + "/logical.gz"]) == raw
            assert r["dirty"] == [u["target"]["name"] for u in units if not u["fresh"]]
            gen, lib = source_images(bs, p, kept)
            shared_elf.add(gen["sha256"])
            all_libs.add(lib["sha256"])
            assert (
                len(
                    [
                        u
                        for u in units
                        if u["target"]["kind"] == ["custom-build"]
                        and "/crates/ruff_unicode_names2#" in u["package_id"]
                        and gen["path"] in u["filenames"]
                    ]
                )
                == 1
                and len(
                    [
                        u
                        for u in units
                        if u["target"]["name"] == "unicode_names2_generator"
                        and lib["path"] in u["filenames"]
                        and u["profile"] == lib["cargo_profile"]
                    ]
                )
                == 1
            )
            if name in SCORE or name == "traced-unchanged":
                primary_libs.add(lib["sha256"])
            if generated is None:
                generated = r["generated"]
            assert (
                generated == r["generated"] == done["sources"]
                and sorted(generated) == ["generated.rs", "generated_alias.rs", "generated_phf.rs"]
                and all(
                    h.sha(gzip.decompress(bs["generated/" + k + ".gz"])) == k
                    for k in generated.values()
                )
            )
            rec = {"dirty_count": len(r["dirty"]), "typed": len(units)}
            if name in SCORE:
                rec["instructions"] = h.hw(get(p + "/whole.json"))
                rec["allocated_B"] = h.disk(bs, p, r["storage"])
                rec["regions"] = region(J(gzip.decompress(bs[p + "/allocated-ledger.gz"])))
                assert (
                    sum(rec["regions"].values()) == rec["allocated_B"]
                    and rec["instructions"] == r["instructions"]
                )
                assert spec[arm]["measurements"][name] == {
                    "whole": rec["instructions"],
                    "unique_target_shared": rec["allocated_B"],
                    "dirty": len(r["dirty"]),
                }
            if name in TRACE:
                rec["native"] = handoffs(bs, p, arm, sdk["tools"], wrapper, cold_profiles[arm])
            visits[name] = rec
        assert (
            shared_elf == {spec[arm]["generator_ELF"]}
            and primary_libs == {spec[arm]["generator_rlib"]}
            and all_libs == set(spec[arm]["independent_generator_rlibs"])
        )
        probe = get(d + "/effective-settings.json")
        assert (
            probe["stdout"] == "true true true\n"
            and codegen(probe["actual_scope"]) == (OPTS[arm], "on", "on")
            and [s for s in probe["supplied_argv"] if "share-generics" in s]
            == ([FLAG] if arm == "Q" else [])
        )
        pair = "AB" if arm in "AB" else "QC"
        other = linked(bs, pair, arm, pair.index(arm))
        for n in ("traced-repeat", "independent-empty"):
            other[n]["handoff"] = verify_other_kernel(
                bs,
                "linked-" + pair + "/opt" + str(pair.index(arm)) + "/" + n,
                arm,
                wrapper,
                sdk["tools"],
                n == "independent-empty",
            )
        allarms[arm] = {
            "check": visits,
            "linked": other,
            "held_check_ELF": next(iter(shared_elf)),
            "held_rlib": next(iter(primary_libs)),
            "independent_rlibs": sorted(all_libs),
            "units": len(graph["units"]),
        }
    assert (
        len(inventory) == len(warnings) == 1
        and len(errors) == 8
        and all(e == errors[0] for e in errors)
    )
    provider = h.providers(bs, get)
    assert provider["runs"] == 18
    cold_flags = provider_flags(bs)
    changed = {}
    for kind, observations, marker in (
        ("cargo_units", graphs, "ruff_unicode_names2_generator"),
        ("cold_compilers", cold_profiles, NAMED),
    ):
        reference = observations["A"]
        changed[kind] = {}
        for left, right in (("A", "B"), ("B", "Q"), ("Q", "C")):
            lhs, rhs = observations[left], observations[right]
            assert lhs.keys() == rhs.keys() == reference.keys()
            changes = {
                k: [lhs[k], rhs[k]]
                for k in lhs
                if sorted(lhs[k], key=repr) != sorted(rhs[k], key=repr)
            }
            expected = int((left, right) != ("B", "Q") or kind == "cold_compilers")
            assert len(changes) == expected and all(marker in item for item in changes)
            if changes and kind == "cold_compilers":
                assert next(iter(changes.values())) == [
                    [[OPTS[left], "on", "on", left == "Q"]],
                    [[OPTS[right], "on", "on", right == "Q"]],
                ]
            changed[kind][left + right] = changes
    data = {}
    for kind in ("check", "linked"):
        keys = (
            SCORE
            if kind == "check"
            else ["cold", "neutral-unchanged", "historical-hunk", "first-unchanged"]
        )
        data[kind] = {}
        for n in keys:
            one = {a: allarms[a][kind][n]["instructions"] for a in CASES[row]}
            data[kind][n] = {
                "A_over_Q": one["A"] / one["Q"],
                "B_over_Q": one["B"] / one["Q"],
                "A_over_C": one["A"] / one["C"],
                "C_over_Q": one["C"] / one["Q"],
                "A_over_B": one["A"] / one["B"],
            }
    first = data["check"]["first-unchanged"]
    q = allarms["Q"]["check"]
    b = allarms["B"]["check"]
    delta = q["first-unchanged"]["allocated_B"] - b["first-unchanged"]["allocated_B"]
    ratio = q["first-unchanged"]["allocated_B"] / b["first-unchanged"]["allocated_B"]
    return {
        "row": row,
        "sequence": CASES[row],
        "host": root["host"],
        "source_direction": details["source_direction"],
        "wrapper": wrapper["sha256"],
        "original_archive": desc,
        "members": len(bs),
        "check_generated": generated,
        "calibrations": len(cal) * 4,
        "conditional_screen": {
            "B_over_Q_above_1": first["B_over_Q"] > 1,
            "A_over_Q_at_least_2": first["A_over_Q"] >= 2,
            "Q_over_B_cold_at_most_1.05": q["cold"]["instructions"] / b["cold"]["instructions"]
            <= 1.05,
            "Q_minus_B_disk_B": delta,
            "Q_over_B_disk": ratio,
            "Q_B_fresh_disk_within_8MiB_1pct": delta <= 8 * (1 << 20) and ratio <= 1.01,
        },
        "ratios": data,
        "arms": allarms,
        "observed_treatment_differences": changed,
        "native_provider_commands": provider["runs"],
        "provider_hold": provider["arms"],
        "signed_provider_rustc_pids": cold_flags,
    }


def main(d):
    out = []
    for row in ("01", "02"):
        f = d / ("share-bridge-" + row)
        desc = J(f.with_suffix(".json").read_bytes())
        bs = open_archive(f.with_suffix(".zip").read_bytes(), desc, row)
        out.append(audit(bs, row, desc))
    assert (
        out[0]["host"] != out[1]["host"]
        and out[0]["check_generated"] == out[1]["check_generated"]
        and out[0]["wrapper"] == out[1]["wrapper"]
    )
    return {
        "registered": HEAD,
        "source": h.SOURCES,
        "rustc": "c79998a5cd143c445a4b2528f20953b176a65c5d",
        "strict_cargo": h.CARGO,
        "fresh_only": True,
        "scope": "Two mirrored native workers; no interval or ordinary B/Q migration claim.",
        "individual": out,
    }


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]) if len(sys.argv) > 1 else D), sort_keys=True, indent=2))
