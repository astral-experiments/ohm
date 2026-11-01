"""Reopen both native output archives from their original observations without a build tree."""

import gzip, json, os, re, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binding as reg
import overlay, ruff
from bootstrap_subject import unit_log


def load(p):
    return json.loads(p.read_bytes())


def streams(where, name):
    rec = load(where / (name + ".json"))
    data = [gzip.decompress((where / (name + "." + n + ".gz")).read_bytes()) for n in ("stdout", "stderr")]
    reg.need(
        [reg.digest(d) for d in data] == [rec["stdout"], rec["stderr"]], "captured native stream mismatch"
    )
    return rec, *data


def reopen(source, logs):
    root = logs / "ast"
    cas = root / "bodies"
    results = {}
    summary = {}
    native = source / "C"
    src = load(native / "native-qualified.json")
    sdk = {k: load(logs / "sdk" / (k + ".json")) for k in ("E", "C")}
    ids = {k: {n: [v[0], v[4], v[3]] for n, v in r["files"].items()} for k, r in sdk.items()}
    driver = src["driver"]
    reg.need(
        (src["old"], src["new"], src["tree"]) == (reg.OLD, reg.NEW, reg.TREE)
        and src["old_driver"] == ids["E"][driver]
        and src["new_driver"] == ids["C"][driver],
        "misidentified native SDK",
    )
    reg.need(
        src["overlay"] == overlay.verify(native / "overlay", ids["E"], ids["C"], driver), "wrong overlay"
    )
    reg.need(
        src["units"] == unit_log((native / "middle.log").read_text(errors="replace"))
        and src["run_make"] == [reg.TEST, "incremental-missing-query-cache"],
        "native source checks missing",
    )
    for case in src["run_make"]:
        s = (native / (case + ".log")).read_bytes()
        q = load(native / (case + ".command.json"))
        reg.need(
            q["argv"][-1] == "tests/run-make/" + case
            and not q["returncode"]
            and q["output_sha256"] == reg.digest(s)
            and s.count(("test [run-make] tests/run-make/" + case + " ... ok").encode()) == 1
            and b"test result: ok. 1 passed; 0 failed;" in s,
            "source run-make",
        )
    gen = load(native / "generations/result.json")
    reg.need(
        src["migration"] == reg.sha(native / "generations/result.json")
        and not gen["emulated_new_header"]
        and len(gen["runs"]) == 18,
        "missing same-stamp/cross-rlib evidence",
    )
    wanted = [
        ("old-empty", "E", "not-loaded", 8),
        ("old-warm", "E", "loaded", 8),
        ("old-to-new", "C", "not-loaded", 11),
        ("new-warm", "C", "loaded", 11),
        ("new-to-old", "E", "not-loaded", 8),
        ("old-warm-again", "E", "loaded", 8),
    ]
    for phase, subject, kind, fmt in wanted:
        (actual,) = [v for v in gen["runs"] if v["name"] == phase]
        (executed,) = [v for v in gen["runs"] if v["name"] == phase + "-native"]
        reg.need(
            actual["role"] == subject
            and "-Zassert-incr-state=" + kind in actual["argv"]
            and not actual["code"]
            and "internal compiler error" not in actual["stderr"]
            and not executed["code"]
            and executed["stdout"] == "17\n"
            and {h[1] for h in gen["written_headers"][phase]} == {fmt},
            "wrong incremental transition " + phase,
        )
    macro_bodies = set()
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        archives = {}
        readers = {}
        for role in ("E", "C"):
            cx = load(native / ("collision-" + role) / "result.json")
            reg.need(
                reg.sha(native / ("collision-" + role) / "result.json") == src["collisions"][role]
                and cx["driver"] == gen["sdk"][role]["driver"] == ids[role][driver][0]
                and len(cx["phases"]) == 8,
                "wrong native collision test",
            )
            live = [v for v in gen["runs"] if v["role"] == role and v["name"] == role + "-native-client"]
            reg.need(
                len(live) == 1 and live[0]["stdout"] == "word 17\n" and live[0]["code"] == 0,
                "missing foreign-rmeta client",
            )
            for phase, branch in ruff.PHASES:
                dest = root / role / phase
                obj = load(dest / "result.json")
                data, body, err = streams(dest, "cargo")
                raw, ls, _ = streams(dest, "root")
                reg.need(
                    obj["branch"] == branch
                    and obj["phase"] == phase
                    and obj["driver"] == ids[role][driver][0]
                    and data["argv"] == ruff.CLI
                    and not data["exit"]
                    and not raw["exit"]
                    and reg.digest(ls) == obj["listing"],
                    "incorrect concrete compiler, command, status or listing",
                )
                out = [json.loads(v) for v in body.splitlines()]
                reg.need(
                    not any(v["reason"] == "compiler-message" for v in out)
                    and set(obj["macros"]) == ruff.MACROS,
                    "unexpected diagnostic or native macro set",
                )
                for key in obj["macros"].values():
                    if key not in macro_bodies:
                        image = ruff.read_body(cas, key)
                        reg.need(
                            image[:6] == b"\x7fELF\x02\x01" and image[16:20] == b"\x03\x00\x3e\x00",
                            "wrong raw native proc macro",
                        )
                        macro_bodies.add(key)
                code = [v for v in out if v["reason"] == "compiler-artifact"]
                reg.need(
                    out[-1] == {"reason": "build-finished", "success": True}
                    and len(code) == len(obj["units"]) == 36
                    and sorted(v["package_id"] for v in out if v["reason"] == "build-script-executed")
                    == ruff.GRAPH["scripts"],
                    "wrong raw Cargo output",
                )
                specs = [
                    [
                        v["package_id"].replace(data["cwd"], "/__ENROLLED_RUFF__"),
                        v["target"]["name"],
                        v["target"]["kind"],
                        v["target"]["crate_types"],
                        v["features"],
                        v["profile"],
                    ]
                    for v in code
                ]
                reconstructed = sorted(zip(specs, code), key=lambda t: json.dumps(t[0], sort_keys=True))
                reg.need(
                    [v[0] for v in reconstructed] == ruff.GRAPH["roles"] == [v[0] for v in obj["units"]]
                    and all(
                        r["fresh"] == u[2]
                        and len(r["filenames"]) == len(u[1])
                        and all(
                            Path(p).as_posix().endswith("/work/" + rel)
                            for p, rel in zip(r["filenames"], u[1])
                        )
                        for (_, r), u in zip(reconstructed, obj["units"])
                    ),
                    "recorded graph disagrees with Cargo",
                )
                reg.need(
                    len([r for r in code if not r["fresh"]])
                    == {"cold-A": 36, "empty-B": 36, "unchanged-B": 0, "edit-B": 1}[phase]
                    and (
                        phase != "edit-B"
                        or [r["target"]["name"] for r in code if not r["fresh"]] == ["ruff_python_ast"]
                    ),
                    "incorrect actual edit scope",
                )
                key = obj["rlib"]
                if key not in archives:
                    f = tmp / "reopen.rlib"
                    f.write_bytes(ruff.read_body(cas, key))
                    archives[key] = ruff.archive(f)
                    f.unlink()
                reg.need(
                    archives[key] == obj["archive"] and len(archives[key]["object_order"]) > 0,
                    "native archive member mismatch",
                )
                ruff.open_obj(ruff.read_body(cas, obj["rmeta"]), ls.decode())
                width = 64 if branch == "A" else 56
                elf = obj["client"]["elf"]
                x = tmp / "checked-reader"
                if elf not in readers:
                    x.write_bytes(ruff.read_body(cas, elf))
                    x.chmod(0o700)
                    readers[elf] = [
                        subprocess.check_output([x, ext], timeout=15).decode().strip()
                        for ext in ("pyi", "qno")
                    ]
                reg.need(
                    readers[elf]
                    == [str(width) + " Some(Stub)", str(width) + " None"]
                    == [obj["client"][q] for q in ("pyi", "qno")],
                    "retained true native client disagrees",
                )
                for ext, expected in zip(("pyi", "qno"), readers[elf]):
                    rc, text, _ = streams(dest, "run-" + ext)
                    reg.need(
                        not rc["exit"] and text == (expected + "\n").encode(), "original native verdict"
                    )
                cxrec, _, bad = streams(dest, "contradictory")
                errors = [
                    r
                    for r in map(json.loads, bad.splitlines())
                    if r.get("level") == "error" and r.get("code")
                ]
                reg.need(
                    cxrec["exit"] == 1
                    and reg.digest(bad) == obj["client"]["negative"]
                    and [
                        (r["code"]["code"], [s["file_name"] for s in r["spans"] if s["is_primary"]])
                        for r in errors
                    ]
                    == [("E0308", [cxrec["argv"][-1]])],
                    "wrong contradictory native source",
                )
                results[role, phase] = obj
            summary[role] = ruff.compare(results, root, role)
    reg.need(
        summary == load(root / "qualified.json")["subjects"]
        and summary["E"]["public"][1] == summary["C"]["public"][1],
        "unexpected final projection",
    )
    for phase, _ in ruff.PHASES:
        e, c = (results[r, phase] for r in ("E", "C"))
        reg.need(
            e["client"] == c["client"]
            and e["macros"] == c["macros"]
            and e["source"] == c["source"]
            and e["build_scripts"] == c["build_scripts"]
            and [v[:2] for v in e["units"]] == [v[:2] for v in c["units"]]
            and e["archive"]["object_order"] == c["archive"]["object_order"]
            and e["archive"]["object_sha256"] == c["archive"]["object_sha256"],
            "cross-compiler inputs or native outputs disagree",
        )
    return {
        "old": reg.OLD,
        "candidate": reg.NEW,
        "source_qa": src["qa"],
        "run": src["run"],
        "drivers": {r: ids[r][driver][0] for r in ids},
        "subjects": summary,
        "actual_roles": len(results),
        "source_result": reg.sha(native / "native-qualified.json"),
        "measurement": None,
    }


if __name__ == "__main__":
    print(json.dumps(reopen(*map(Path, sys.argv[1:])), sort_keys=True))
