"""Independently reopen one official 55-member run, its native programs and real process images."""

import argparse
import gzip
import hashlib
import json
import mmap
import os
import shutil
import struct
import subprocess
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


def sha(x):
    return hashlib.sha256(x).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def record(z, name):
    return json.loads(
        gzip.decompress(z.read(name)) if name.endswith(".gz") else z.read(name)
    )


def msgs(z, name):
    return [
        json.loads(line) for line in z.read(name).splitlines() if line.startswith(b"{")
    ]


def checked_pmu(rec):
    assert (
        rec["status"] == 0
        and rec["instructions"] > 0
        and rec["enabled"] == rec["running"] > 0
    )
    return rec["instructions"]


def flag(args, key):
    return args[args.index(key) + 1] if key in args else None


def epoch_rows(z, path, files, *, expected=None):
    projects = {"full", "test", "metadata", "link-only"}
    true_rustc = tuple(files["bin/rustc"][2:])
    true_wild = tuple(
        files["lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"][2:]
    )
    spawn = {}
    images = {}
    in_group = defaultdict(list)
    bill = defaultdict(lambda: [0, 0, 0])
    outer = []
    monitors = []
    bad = []
    for line in z.read(path + "/tasks/epochs.tsv").decode().splitlines():
        parts = line.split()
        which = parts[0]
        if which == "F":
            p, caller, c, event = map(int, parts[1:])
            assert c not in spawn
            spawn[c] = p
        elif which == "C":
            ep, tg, tid, ins, en, running = map(int, parts[1:])
            assert min(ins, en, running) >= 0
            if en < running:
                bad.append([ep, tg, tid, ins, en, running])
            for i, value in enumerate([ins, en, running]):
                bill[ep][i] += value
        elif which == "I":
            _, ep, tg, tid, mono, reason = parts
            ep, tg, tid = map(int, (ep, tg, tid))
            assert reason in ("first", "exec") and ep not in images
            name = f"{ep:05}.nul"
            raw = z.read(path + "/tasks/" + name)
            fields = raw.split(b"\0")
            assert fields[-1] == b"" and int(fields[0]) == tg
            key = tuple(map(int, fields[1:3]))
            exe = os.fsdecode(fields[3])
            args = list(map(os.fsdecode, fields[4:-1]))
            mode = "other"
            crate = None
            out = None
            if key == true_rustc:
                crate = flag(args, "--crate-name")
                only = any(
                    a in ("-Zlink-only", "-Zlink-only=yes")
                    or (
                        i
                        and args[i - 1] == "-Z"
                        and a in ("link-only", "link-only=yes")
                    )
                    for i, a in enumerate(args)
                )
                rlink = [
                    a
                    for a in args[1:]
                    if not a.startswith("-") and a.endswith(".rlink")
                ]
                assert not only or len(rlink) == 1
                mode = (
                    "link-only"
                    if only
                    else "config"
                    if not crate
                    else "test"
                    if "--test" in args
                    else "metadata"
                    if any(
                        a.startswith("--emit=")
                        and "link" not in a.removeprefix("--emit=").split(",")
                        for a in args
                    )
                    else "full"
                )
                if only and not crate:
                    crate = Path(rlink[0]).stem
            elif key == true_wild:
                mode = "Wild"
                out = flag(args, "-o") or next(
                    (a[9:] for a in args if a.startswith("--output=")), None
                )
                assert out
            images[ep] = dict(
                epoch=ep,
                pid=tg,
                tid=tid,
                reason=reason,
                exe=exe,
                dev=key[0],
                ino=key[1],
                mode=mode,
                crate=crate,
                output=out,
                argv_sha256=sha(raw),
                argv=name,
            )
            if reason == "exec":
                in_group[tg].append(ep)
        elif which == "M":
            assert len(parts) == 3 and min(map(int, parts[1:])) > 0
            monitors.append(parts)
        else:
            assert which == "W"
            outer.append(list(map(int, parts[1:])))
    assert (
        len(outer) == 1
        and outer[0][0] > 0
        and outer[0][-1] == 0
        and not set(bill) - set(images)
    )
    assert len(monitors) == 1
    for ep, i in images.items():
        i["counter"] = bill[ep]
        if i["mode"] == "Wild" and i["reason"] == "exec":
            pid = i["pid"]
            seen = set()
            owner = None
            while pid in spawn:
                assert pid not in seen
                seen.add(pid)
                pid = spawn[pid]
                possible = [
                    k
                    for k in in_group[pid]
                    if k <= ep and images[k]["mode"] in projects
                ]
                if possible:
                    owner = possible[-1]
                    break
            assert owner
            i["owner_epoch"] = owner
            i["owner_mode"] = images[owner]["mode"]
            i["owner_crate"] = images[owner]["crate"]
    if expected:
        ex = {x["epoch"]: x for x in expected["roles"]}
        assert (
            set(ex) == set(images)
            and expected["outer"] == outer[0]
            and expected["logical_forks"] == len(spawn)
        )
        for ep, i in images.items():
            orig = ex[ep]
            for k in ("pid", "tid", "dev", "ino", "argv_sha256", "counter"):
                assert i[k] == orig[k]
            assert (i["exe"], i["reason"]) == (orig["path"], orig["trigger"])
            if i["mode"] != "other":
                assert (i["mode"], i["crate"]) == (orig["mode"], orig["crate"])
            if i["mode"] == "Wild" and i["reason"] == "exec":
                assert (i["owner_epoch"], i["output"]) == (
                    orig["owning_rustc_epoch"],
                    orig["output"],
                )
    interesting = [
        i
        for i in images.values()
        if i["reason"] == "exec" and i["mode"] in projects | {"Wild"}
    ]
    return {
        "all_images": len(images),
        "forks": len(spawn),
        "outer": outer[0],
        "refused_pmu_rows": bad,
        "observed": interesting,
        "modes": dict(Counter(i["mode"] for i in interesting)),
        "full": dict(
            Counter(i["crate"] for i in interesting if i["mode"] in ("full", "test"))
        ),
        "wild_owners": dict(
            Counter(i["owner_crate"] for i in interesting if i["mode"] == "Wild")
        ),
        "tracked_crate_local_ir": {
            k: sum(
                i["counter"][0]
                for i in interesting
                if i["crate"] == k and i["mode"] in ("full", "test", "metadata")
            )
            for k in ("ron", "insta", "insta_cmd")
        },
    }


def elf_record(file):
    with file.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as buf:
        assert buf[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", buf, 18) == (
            62,
        )
        offset = struct.unpack_from("<Q", buf, 40)[0]
        width, number, strings = struct.unpack_from("<HHH", buf, 58)

        def sh(i):
            return struct.unpack_from("<IIQQQQIIQQ", buf, offset + i * width)

        _, _, _, _, p, n, *_ = sh(strings)
        table = buf[p : p + n]
        secs = []
        for i in range(number):
            e = sh(i)
            name = table[e[0] : table.index(b"\0", e[0])].decode()
            assert e[1] == 8 or e[4] + e[5] <= len(buf)
            secs.append(
                [
                    name,
                    e[1],
                    e[2],
                    e[5],
                    None if e[1] == 8 else sha(memoryview(buf)[e[4] : e[4] + e[5]]),
                ]
            )
        return {"sha256": sha(buf), "bytes": len(buf), "sections": secs}


def saved_native(z, role, images):
    result = {}
    for h, r in images.items():
        compressed = (role + "/" if role else "") + h + ".elf.zst"
        assert compressed in z.namelist()
        with tempfile.TemporaryDirectory() as temporary:
            tmp = Path(temporary)
            zipdata = tmp / "program.zst"
            elf = tmp / "program"
            with z.open(compressed) as src, zipdata.open("xb") as out:
                shutil.copyfileobj(src, out)
            with elf.open("xb") as out:
                subprocess.run(["zstd", "-dq", "-c", zipdata], stdout=out, check=True)
            got = elf_record(elf)
            assert got == r
            result[h] = {
                "file_bytes": got["bytes"],
                "section_count": len(got["sections"]),
                "physical_sections_digest": sha(
                    json.dumps(got["sections"], separators=(",", ":")).encode()
                ),
            }
    return result


def roles(z, role, sdk, reported, plan, *, native_reader=saved_native):
    modes = [
        "old",
        "edit",
        "first-unchanged",
        "second-unchanged",
        "repair",
        "independent-empty",
    ]
    probe = "separate-unchanged-observed"
    full = not reported["census_refusal"]
    labels = modes + ([probe] if full else [])
    ledgers = {}
    positions = {}
    decs = {}
    bodies = {}
    pmu = {}
    graphs = {}
    graph = record(z, role + "/metadata.json.gz")
    assert len(set(graph["workspace_members"])) == 55 and set(
        graph["workspace_members"]
    ) == set(graph["workspace_default_members"])
    graph_names = {v["id"]: v["name"] for v in graph["packages"]}
    assert set(graph_names) == set(graph["workspace_members"])
    source = record(z, role + "/registry.json.gz")
    assert len(source) > 400 and all(len(v) == 64 for v in source.values())
    for lab in labels:
        loc = role + "/" + lab
        rs = msgs(z, loc + "/stdout.jsonl")
        assert rs[-1] == {"reason": "build-finished", "success": True}
        inv = record(z, loc + "/inventory.json.gz")
        assert inv["state"] == (plan["old"] if lab == "old" else plan["new"])
        units = []
        products = {}
        for row in rs:
            if row["reason"] != "compiler-artifact":
                continue
            t = row["target"]
            u = [
                row["package_id"],
                t["name"],
                t["kind"],
                sorted(row["features"]),
                row["profile"]["test"],
            ]
            units.append([u, row["fresh"]])
            if row.get("executable"):
                whole = row["executable"]
                s = whole.split("/ohm-foreign-join/")
                assert len(s) == 2 and s[1] not in products
                products[s[1]] = u
        assert (
            sorted(units, key=repr) == inv["units"]
            and len(units) == reported["units"][lab] == 623
        )
        assert (
            products == {p: x["unit"] for p, x in inv["executables"].items()}
            and len(products) == reported["products"][lab] == 102
        )
        path = inv["binary"]
        assert (
            products[path][1:3] == ["e2e", ["test"]]
            and graph_names[products[path][0]] == "ty_server"
        )
        images = inv["executables"]
        e = images[path]["elf"]
        h = e["sha256"]
        assert h == reported["natives"][lab]
        assert h not in bodies or bodies[h] == e
        bodies[h] = e
        ledgers[lab] = images
        positions[lab] = path
        graphs[lab] = {
            "typed": len(units),
            "nominal_dirty": sum(1 for _, fresh in units if not fresh),
            "dirty_names": Counter(u[1] for u, fresh in units if not fresh),
            "executables": len(products),
            "e2e": h,
        }
        if lab != "separate-unchanged-observed":
            pmu[lab] = checked_pmu(record(z, loc + "/hardware.json"))
            assert pmu[lab] == reported["whole"][lab]
    for label in ("invalid", "invalid-again"):
        loc = role + "/" + label
        rs = msgs(z, loc + "/stdout.jsonl")
        assert (
            rs[-1] == {"reason": "build-finished", "success": False}
            and record(z, loc + "/resources.json")["exit"] == 101
        )
        assert any(
            m["reason"] == "compiler-message"
            and (m["message"].get("code") or {}).get("code") == "E0308"
            and any(
                t["is_primary"] and t["file_name"].endswith("/ty_server/src/session.rs")
                for t in m["message"]["spans"]
            )
            for m in rs
        )
        assert not any(
            m["reason"] == "compiler-artifact"
            and "ty_server" in m["package_id"]
            and m["target"]["name"] == "e2e"
            and m["target"]["kind"] == ["test"]
            for m in rs
        )
    for label, rc in [
        ("old-native", 0),
        ("old-on-edit", 101),
        ("edit-native", 0),
        ("settled-native", 0),
        ("repair-native", 0),
        ("empty-native", 0),
    ]:
        prefix = role + "/" + label + "/"
        names = z.read(prefix + "test-list")
        stdout = z.read(prefix + "stdout")
        assert (
            sha(names) == reported["names"]
            and sum(x.endswith(b": test") for x in names.splitlines()) >= 100
        )
        assert (b"1 passed;" if rc == 0 else b"1 failed;") in stdout and (
            rc == 0 or b"script_tag" in stdout and b"source_text" in stdout
        )
    physically = native_reader(z, role, bodies)
    assert (
        len({v["e2e"] for k, v in graphs.items() if k != "old"}) == 1
        or not reported["e2e_exact"]
    )
    assert (
        len({v["e2e"] for k, v in graphs.items() if k != "old"}) == 1
        and graphs["old"]["e2e"] != graphs["edit"]["e2e"]
    ) == reported["e2e_exact"]
    for k, images in ledgers.items():
        clean = ledgers["independent-empty"]
        assert set(images) == set(clean)
        different = {}
        for path, x in images.items():
            orig = x["elf"]
            current = clean[path]["elf"]
            assert all(
                len(v["sha256"]) == 64 and v["bytes"] > 0 for v in (orig, current)
            )
            if orig["sha256"] != current["sha256"]:
                # Only the selected e2e was retained whole. This classifies each separately captured section digest for the rest.
                old = {v[0]: v[1:] for v in orig["sections"]}
                new = {v[0]: v[1:] for v in current["sections"]}
                assert len(old) == len(orig["sections"]) and len(new) == len(
                    current["sections"]
                )
                different[path] = {
                    "old": orig["sha256"],
                    "clean": current["sha256"],
                    "changed_section_payloads": sorted(
                        name
                        for name in old.keys() | new.keys()
                        if old.get(name) != new.get(name)
                    ),
                }
        assert sorted(different) == reported["changed_executables_vs_clean"][k]
        decs[k] = different
    census = epoch_rows(
        z,
        role + "/" + probe,
        sdk["files"],
        expected=record(z, role + "/" + probe + "/owner-census.json.gz")
        if full
        else None,
    )
    return {
        "typed": graphs,
        "whole": pmu,
        "native_files": physically,
        "native_names": reported["names"],
        "e2e_exact": reported["e2e_exact"],
        "registry_count": len(source),
        "registry_digest": sha(json.dumps(source, sort_keys=True).encode()),
        "native_differences": decs,
        "census": census,
        "original_census_refusal": reported["census_refusal"],
        "edited_full_inventory": {
            k: v["elf"]["sha256"] for k, v in ledgers["edit"].items()
        },
    }


def read(raw, artifact, head, run, suite, block):
    assert (
        raw.stat().st_size == artifact["size_in_bytes"]
        and artifact["workflow_run"]["id"] == run
    )
    with raw.open("rb") as f:
        assert (
            "sha256:" + hashlib.file_digest(f, "sha256").hexdigest()
            == artifact["digest"]
        )
    with zipfile.ZipFile(raw) as z:
        assert len(z.namelist()) == len(set(z.namelist())) and z.testzip() is None
        plan = load(suite / "workspace-enrollment.json")
        enrollment = record(z, "admission.json")
        assert (
            enrollment["head"] == head
            and int(enrollment["run"]) == run
            and enrollment["study"] == plan
            and enrollment["order"] == plan["orders"][block]
        )
        sdk = record(z, "sdk-24.json")
        spec = load(suite / "release-compiler.json")
        assert (
            sdk["archive"]["sha256"]
            == "sha256:" + spec["tar_sha256"]
            == "sha256:" + plan["sdk_archive"]
            and len(sdk["files"]) == len(spec["members"]) == 79
        )
        for path, x in spec["members"].items():
            assert sdk["files"][path][0] == x["sha256"] and sdk["files"][path][-1] > 0
        source = record(z, "matched-source.json")
        p = load(suite / "pricing.json")
        assert (
            source["qa"] == p["producer_head"]
            and int(source["run"]) == p["producer_run"]
            and {k: v["sha256"] for k, v in source["cargo"].items()} == p["cargo"]
        )
        assert (
            1.99
            < checked_pmu(record(z, "calibration-fork.json"))
            / checked_pmu(record(z, "calibration-single.json"))
            < 2.01
        )
        v = record(z, "result.json")
        assert set(v) == {"parent", "candidate"}
        r = {role: roles(z, role, sdk, v[role], plan) for role in v}
        assert r["parent"]["registry_digest"] == r["candidate"]["registry_digest"]
        return {
            "boot": enrollment["boot"],
            "block": block,
            "source": source,
            "roles": r,
            "cross_role_edited_unequal": sorted(
                k
                for k, v in r["parent"]["edited_full_inventory"].items()
                if r["candidate"]["edited_full_inventory"][k] != v
            ),
            "primary_ratio": r["parent"]["whole"]["first-unchanged"]
            / r["candidate"]["whole"]["first-unchanged"],
        }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--suite", type=Path, required=True)
    a = ap.parse_args()
    meta = load(a.folder / "run.json")
    art = load(a.folder / "artifacts.json")["artifacts"]
    expected = load(a.folder / "expected.json")
    assert (
        meta["head_sha"] == expected["head"]
        and meta["id"] == expected["run"]
        and meta["run_attempt"] == 1
        and meta["event"] == "workflow_dispatch"
    )
    result = {}
    for block in ("PC", "CP"):
        (item,) = [
            x for x in art if x["name"] == f"insta-workspace-{block}-{meta['id']}"
        ]
        result[block] = read(
            a.folder / ("workspace-" + block + ".zip"),
            item,
            meta["head_sha"],
            meta["id"],
            a.suite,
            block,
        )
    assert len({r["boot"] for r in result.values()}) == 2
    (a.folder / "verified.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({k: v["primary_ratio"] for k, v in result.items()}))
