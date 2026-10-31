"""Reopen the acquired raw compiler probes and compare P/C at the same profile."""

from pathlib import Path
import argparse, ast, gzip, io, json, os, re, sys, zipfile

D = Path(__file__).resolve().parent
sys.path[:0] = [str(D), str(D.parent)]
import formats as f, signed_readers as h
from native_rows import native, GEN
from opened_driver import inspect
from decision import cohort

J = h.read
RUN = 41160280371
HEAD = "04814d7aa6fb80e2f6fafe5253fd7a559a793e10"
ORDER = {"01": "P0 C0 C1 P1 P2 C2".split(), "02": "C2 P2 P1 C1 C0 P0".split()}
DIR = {"01": "reverse", "02": "forward"}
SHA = {
    "P": "b83289a6adecf1a24b790dcff1a42d77337909349c5745677485f8e914627447",
    "C": "5af5a6a20ccb67bdf4196ca2f3df5677ce19076f66110a955e903e32b124889c",
}
GENFILES = {
    "generated.rs": "9b5eca67ab5970e513c5eb40dab5e9418f981cb0bc62167604396e760dc1184f",
    "generated_alias.rs": "9f5a28cda43b481b11d8dc6e1bf0f7579cacdf9489e3166ce6e3144a5d017e9f",
    "generated_phf.rs": "4812faa3a82d2a02ac004df2fbde343185927dd71dce1d6cf23b22e94385b855",
}
SEAL = J((D.parent / "custody/inputs/native-seal.json").read_bytes())
SCORE = ("cold", "neutral-unchanged", "historical-edit", "first-unchanged")
ORD = ("warm-invalid", "warm-repair", "empty-invalid", "empty-repair")
TRACE = {"traced-unchanged": "check-repeat", "empty-edited": "check-cold"}
CFG = {
    "0": None,
    **{
        k: "[profile.dev.package.ruff_unicode_names2_generator]\nopt-level = "
        + k
        + "\n"
        for k in "12"
    },
}
KEYS = {
    "RUSTFLAGS",
    "CARGO_ENCODED_RUSTFLAGS",
    "CARGO_BUILD_RUSTFLAGS",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "RUSTC_BOOTSTRAP",
    "CI",
    "TF_BUILD",
    "OHM_BRIDGE_ARM",
    "CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "QUALIFICATION_TOKEN",
}
CMD = "cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json".split()
LEVL = {"0": "A", "1": "B", "2": "C"}
NAMES = {"P": "parent", "C": "candidate"}


def opened(contents, obj, row):
    assert obj["name"] == "actual-compiler-loop-" + row
    assert obj["size_in_bytes"] == len(contents) and obj["digest"] == "sha256:" + h.sha(
        contents
    )
    assert (obj["workflow_run"]["id"], obj["workflow_run"]["head_sha"]) == (RUN, HEAD)
    with zipfile.ZipFile(io.BytesIO(contents)) as z:
        assert z.testzip() is None and z.namelist() == [obj["name"] + ".tar.gz"]
        return h.unpack(z.read(z.namelist()[0]))


def products(bs, get, sub, reg):
    all_selections = get("all-selections.json")
    roles = {}
    sdk = {}
    for r in "PC":
        m = get("native-manifest-" + r + ".json")
        store = get("native-storage-" + r + ".json")
        ref = SEAL["roles"][NAMES[r]]
        for field in ("commit", "tree", "transfer"):
            assert m[field] == ref[field]
        assert m["role"] == NAMES[r] and m["qa"] == SEAL["head"]
        assert len(m["files"]) == store["files"] == 68
        assert store["logical_files_B"] == sum(v[1] for v in m["files"].values())
        assert store["archive_physical_B"] >= store["logical_files_B"]
        assert m["files"][store["driver"]][0] == SHA[r]
        assert (
            m["files"]["bin/rustc"][0]
            == "8bfdc9779937e9cd2c9ef5db9f50cee9aab03ddec5672b37a3a3c9278cf1f5d0"
        )
        assert (
            m["files"]["bin/cargo"][0] == h.FIXED
            and m["files"]["lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"][0]
            == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
        )
        sdk[r] = {**store, "source": ref, "driver_sha": SHA[r]}
    for j, entry in enumerate(all_selections):
        role = entry["role"]
        base = entry["record"]
        assert base == f"selection-{j}-{role}"
        s = get(base + "/selection.json")
        tools = entry["tools"]
        assert (
            tools == s["tools"]
            and entry["version"] == s["version"]
            and s["role"] == role
        )
        assert s["tree"] == SEAL["roles"][NAMES[role]]["tree"] and s["kit_files"] == 68
        assert h.CARGO in s["cargo"] and s["version"].startswith("rustc 1.99.0-dev\n")
        assert (
            tools["driver"]["sha256"] == SHA[role]
            and tools["cargo"]["sha256"] == h.FIXED
        )
        assert roles.setdefault(role, tools) == tools
        actual = [
            m[1]
            for m in re.finditer(
                r'(?m)^.*?openat2?\([^"]*"([^"]*librustc_driver[^"]*)"[^\n]*\)\s+=\s*[0-9]+$',
                bs[base + "/real-open.tsv"].decode(),
            )
        ]
        assert s["driver_opens"] == actual and actual
    assert roles["P"]["driver"]["dev_ino"] != roles["C"]["driver"]["dev_ino"]
    assert roles["P"]["driver"]["file"] == roles["C"]["driver"]["file"]
    return roles, sdk


def driver_proof(bs, root, enrollment, tools, name):
    v = J(bs[root + "/actual-cargo-driver/verified.json"])
    assert (
        v["role"] == name
        and v["sha256"] == SHA[name]
        and v["dev_ino"] == tools["driver"]["dev_ino"]
    )
    real = Path(tools["rustc"]["file"]).parent.parent
    link = Path(enrollment["environment"]["RUSTUP_HOME"]) / "toolchains/ohm"

    def resolved(p):
        p = Path(os.path.normpath(p))
        return real / p.relative_to(link) if p.is_relative_to(link) else p

    with gzip.GzipFile(
        fileobj=io.BytesIO(bs[root + "/actual-cargo-driver/all-process-opens.gz"])
    ) as stream:
        found = inspect(
            stream,
            lambda p: resolved(p) == Path(tools["rustc"]["file"]),
            lambda p: resolved(p) == Path(tools["driver"]["file"]),
        )
    assert found == v["full_rustcs_opening_it"] and sorted(x[1] for x in found) == [
        "build_script_build",
        "ron",
        "unicode_names2",
    ]
    return found


def check_visit(bs, loc, label, role, sub, prior, tools, good, warn, errs, elfs):
    v = J(bs[loc + "/visit.json"])
    bad = label.endswith("invalid")
    assert v["arm"] == role and v["phase"] == label and v["exit"] == (101 if bad else 0)
    assert v["source"] == sub[0 if label in ("cold", "neutral-unchanged") else 1]
    typed = [J(line) for line in gzip.decompress(bs[loc + "/stdout.gz"]).splitlines()]
    assert typed[-1] == {"reason": "build-finished", "success": not bad}
    cargo = [j for j in typed if j["reason"] == "compiler-artifact"]
    em = [j["message"] for j in typed if j.get("message", {}).get("level") == "error"]
    assert [u["target"]["name"] for u in cargo if not u["fresh"]] == v["dirty"]
    assert len(cargo) == v["typed"] and not any(u["executable"] for u in cargo)
    common = sorted(
        {
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
        }
    )
    body = json.dumps(common, separators=(",", ":")).encode()
    assert (
        gzip.decompress(bs[loc + "/logical.gz"]) == body
        and h.sha(body) == v["logical_sha"]
    )
    assert em == v["errors"] and len(em) == int(bad)
    if bad:
        e = em[0]
        assert e["code"]["code"] == "E0308" and any(
            s["is_primary"]
            and s["file_name"] == "crates/ty_project/src/lib.rs"
            and "OHM_HOST_PROFILE_BAD_TYPE" in "".join(x["text"] for x in s["text"])
            for s in e["spans"]
        )
        errs.append(e)
    else:
        assert len(cargo) == 303
        good.add(v["logical_sha"])
        warn.add(tuple(v["warning_sha"]))
    assert v["error_source"] == (
        "7d2b2aae03e2ecd08e8767521543341dffc8e0cb3cd55cfbe4d89228daa230dc"
        if bad
        else "d560695aa852f6f95c0218c0aba27aecd10e1d26980d9b4679e51d08ab69d309"
    )
    assert v["method"] == (
        "score" if label in SCORE else "trace" if label in TRACE else "ordinary"
    )
    assert v["warning_sha"] == sorted(
        h.sha(json.dumps(r["message"], sort_keys=True).encode())
        for r in typed
        if r.get("message", {}).get("level") == "warning"
    )
    assert v["generated"] == GENFILES
    for sha in GENFILES.values():
        assert h.sha(gzip.decompress(bs["generated/" + sha + ".gz"])) == sha
    prog, lib = f.source_images(bs, loc, elfs)
    assert (
        sum(
            u["target"]["name"] == "unicode_names2_generator"
            and lib["path"] in u["filenames"]
            and u["profile"] == lib["cargo_profile"]
            for u in cargo
        )
        == 1
    )
    assert (
        sum(
            u["target"]["kind"] == ["custom-build"]
            and "/crates/ruff_unicode_names2#" in u["package_id"]
            and prog["path"] in u["filenames"]
            for u in cargo
        )
        == 1
    )
    out = {
        "typed": v["typed"],
        "dirty": len(v["dirty"]),
        "generator_elf": prog["sha256"],
        "generator_rlib": lib["sha256"],
    }
    if label in SCORE:
        out["instructions"] = h.hw(J(bs[loc + "/whole.json"]))
        assert out["instructions"] == v["instructions"]
        out["allocated_B"] = h.disk(bs, loc, v["storage"])
        out["regions"] = f.region(J(gzip.decompress(bs[loc + "/allocated-ledger.gz"])))
        assert sum(out["regions"].values()) == out["allocated_B"] and not any(
            k.startswith(loc + "/kernel/") for k in bs
        )
    if label in TRACE:
        p, levelmap, switch = native(bs, loc, tools, LEVL[role[1]], TRACE[label])
        check = h.trace(bs, loc, tools, v)
        assert p["full"] == check["full"] and p["wild"] == check["wild"]
        out["physical"] = p
        out["physical"].pop("selected_signed_compilers")
        if label == "empty-edited":
            prior[role] = [levelmap, switch]
    return out


def audit(bs, row, meta):
    get = lambda n: J(bs[n])
    reg = get("actual-compiler-enrollment.json")
    sub = get("initial-acquisition-subjects.json")
    init = get("initial-acquisition-strict.json")
    final = get("complete.json")
    assert (
        reg["row"] == final["row"] == row
        and reg["sequence"] == final["sequence"] == ORDER[row]
    )
    assert (
        int(reg["run"]) == RUN and reg["head"] == HEAD and reg["direction"] == DIR[row]
    )
    assert (
        reg["plan"] == h.sha((D.parent / "PLAN.md").read_bytes())
        and reg["seal"] == get("compiler-source-seal.json") == SEAL
    )
    assert (
        h.SOURCES == sub["source"] == reg["source"]
        and h.PATCH == sub["history"] == reg["history"]
    )
    assert (
        reg["check"] == CMD
        and reg["configs"] == CFG
        and not (KEYS & reg["environment"].keys())
    )
    assert set(reg["environment"]) == {
        "CARGO_BUILD_BUILD_DIR",
        "CARGO_BUILD_JOBS",
        "CARGO_HOME",
        "CARGO_NET_OFFLINE",
        "CARGO_TARGET_DIR",
        "CARGO_TERM_COLOR",
        "GIT_OPTIONAL_LOCKS",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "RUSTUP_AUTO_INSTALL",
        "RUSTUP_HOME",
        "TMPDIR",
        "USER",
    }
    assert len(init["locked"]) == 498 and len(get("host.json")["actual"]) == 8
    assert final["all_sources"] == GENFILES and final["ordinary"]
    cal = f.calibration(bs)
    roles, sdk = products(bs, get, sub, reg)
    before, after = sub["original_blob"], sub["historical_parent_blob"]
    direction = (before, after) if row == "01" else (after, before)
    graphs = {}
    native_opts = {}
    results = {}
    good = set()
    warn = set()
    errs = []
    held = {}
    for role in ORDER[row]:
        r, lv = role
        root = "opt" + role
        tools = roles[r]
        assert get(root + "/runtime.json")["tools"] == tools
        graph = J(gzip.decompress(bs[root + "/unit-graph.json.gz"]))
        graphs[role] = f.unit_profiles(graph)
        elfs = set()
        visits = {}
        for phase in (*SCORE, *TRACE, *ORD):
            visits[phase] = check_visit(
                bs,
                root + "/" + phase,
                phase,
                role,
                direction,
                native_opts,
                tools,
                good,
                warn,
                errs,
                elfs,
            )
        assert len(elfs) == 1
        held[role] = elfs.pop()
        decisions = get(root + "/checks.json")
        assert (
            decisions["stdout"] == "true true true\n"
            and f.codegen(decisions["actual_scope"]) == (lv, "on", "on")
            and not any("share-generics" in a for a in decisions["actual_scope"])
        )
        found = driver_proof(bs, root, reg, tools, r)
        linked = f.linked(bs, "opt" + lv, role, "PC".index(r))
        prefix = "linked-opt" + lv + "/opt" + str("PC".index(r))
        assert get(prefix + "/runtime.json")["tools"] == tools
        for phase, roster in (
            ("independent-empty", "build-cold"),
            ("traced-repeat", "build-repeat"),
        ):
            p, _, _ = native(bs, prefix + "/" + phase, tools, LEVL[lv], roster)
            p.pop("selected_signed_compilers")
            linked[phase]["physical"] = p
        defined, imports = (
            gzip.decompress(bs[root + "/library-symbols-" + n + ".gz"])
            for n in ("defined", "imported")
        )
        results[role] = {
            "check": visits,
            "build": linked,
            "actual_cargo_driver_pids": found,
            "generator_symbols": [
                len(defined.splitlines()),
                len(imports.splitlines()),
                h.sha(defined),
                h.sha(imports),
            ],
        }
    assert (
        len(errs) == 12
        and all(e == errs[0] for e in errs)
        and len(good) == len(warn) == 1
    )
    assert get("check-verified.json")["neutral_elf"] == held
    for lv in "012":
        assert graphs["P" + lv] == graphs["C" + lv]
        ll, rr = native_opts["P" + lv], native_opts["C" + lv]
        for a, b in zip(ll, rr):
            assert a.keys() == b.keys() and all(
                sorted(a[k], key=repr) == sorted(b[k], key=repr) for k in a
            )
    for role in "PC":
        base = graphs[role + "0"]
        for lv in "12":
            new = graphs[role + lv]
            assert base.keys() == new.keys()
            (changed,) = [k for k in base if base[k] != new[k]]
            assert (
                "ruff_unicode_names2_generator" in changed
                and len(base[changed]) == len(new[changed]) == 1
            )
            assert base[changed][0] | {"opt_level": lv} == new[changed][0]
    verified = get("same-profile-decision.json")
    for kind, rows in verified["same_profile"].items():
        edit = "historical-edit" if kind == "check" else "historical-hunk"
        for lv, ph in rows.items():
            for endpoint, cells in ph.items():
                legs = (
                    (edit, "first-unchanged")
                    if endpoint == "edit_plus_repeat"
                    else (endpoint,)
                )
                for r, cn in NAMES.items():
                    observed = results[r + lv][kind]
                    assert cells[cn] == [
                        sum(observed[n]["instructions"] for n in legs),
                        observed[legs[-1]]["allocated_B"],
                    ]
                assert (
                    cells["same_profile_P_over_C"]
                    == cells["parent"][0] / cells["candidate"][0]
                )
                assert (
                    cells["candidate_minus_parent_allocated_B"]
                    == cells["candidate"][1] - cells["parent"][1]
                )
    provider = h.providers(bs, get)
    for idx in (0, 1):
        for name in ("held-83", "held-47", "malformed", "remove"):
            stream = gzip.decompress(
                bs[f"native-provider/opt{idx}/empty/{name}/exec-and-provider-open.gz"]
            )
            candidates = []
            for line in stream.splitlines():
                if GEN.encode() not in line:
                    continue
                mt = re.match(
                    rb'^\S+ (\d+) execve\("([^"]+)", (\[.*\]), .*\)\s+= 0$', line
                )
                if not mt:
                    continue
                argv = ast.literal_eval(mt[3].decode())
                exe = Path(os.fsdecode(mt[2]))
                if (
                    exe.name == "rustc"
                    and "--crate-name" in argv
                    and argv[argv.index("--crate-name") + 1]
                    == "unicode_names2_generator"
                ):
                    assert f.codegen(argv) == ("1", "on", "on") and not any(
                        "share-generics" in a for a in argv
                    )
                    candidates.append(int(mt[1]))
            assert len(candidates) == 1
    return {
        "row": row,
        "host": reg["host"],
        "archive": meta,
        "members": len(bs),
        "calibrations": len(cal) * 4,
        "roles": results,
        "sources": reg["source"],
        "sdk": sdk,
        "generated": GENFILES,
        "neutral_elf": held,
        "providers": provider,
        "error_sha": h.sha(json.dumps(errs[0], sort_keys=True).encode()),
        "counters": verified,
    }


def final(workers):
    assert {v["row"] for v in workers} == {"01", "02"} and len(
        {v["host"] for v in workers}
    ) == 2
    left, right = workers
    return {
        "head": HEAD,
        "run": RUN,
        "workers": workers,
        "decision": cohort(left["counters"], right["counters"]),
        "same_neutral_elf_across_hosts": left["neutral_elf"] == right["neutral_elf"],
    }


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("source", nargs="?", type=Path, default=D)
    args.add_argument(
        "--run",
        type=int,
        default=RUN,
        help="A fresh manual run of the exact same workflow revision",
    )
    chosen = args.parse_args()
    source, RUN = chosen.source, chosen.run
    rows = []
    for row in ORDER:
        src = source / ("actual-compiler-loop-" + row)
        desc = J(src.with_suffix(".json").read_bytes())
        rows.append(
            audit(opened(src.with_suffix(".zip").read_bytes(), desc, row), row, desc)
        )
    print(json.dumps(final(rows), sort_keys=True, indent=2))
