"""Independently reopen package QA 41163268493, including whole native Cargo, selectors and edge controls."""

from pathlib import Path
import gzip
import io
import json
import os
import re
import sys
import zipfile

D = Path(__file__).resolve().parent
HEAD = "d3193d6417188200e84ca6d12a140de5ed3a94f8"
RUN = 41163268493
BASE = D.parent
sys.path[:0] = [str(BASE), str(BASE.parent)]
import reopen as old
from opened_driver import inspect
from native_rows import native

h, f = old.h, old.f
J = h.read
CMD = "cargo +ohm build -p ruff_unicode_names2 --lib --locked --offline -j4 --message-format=json".split()
GEN = old.GENFILES
EXPECTED = "Some(0)\nSome(0)\nSome(65)\nSome(9731)\n"
SUBPATH = "crates/ruff_unicode_names2/src/lib.rs"


def opened(zipbytes, obj, row):
    assert (
        obj["name"] == "supported-linked-" + row
        and obj["digest"] == "sha256:" + h.sha(zipbytes)
        and obj["size_in_bytes"] == len(zipbytes)
    )
    assert (obj["workflow_run"]["id"], obj["workflow_run"]["head_sha"]) == (RUN, HEAD)
    with zipfile.ZipFile(io.BytesIO(zipbytes)) as z:
        assert z.testzip() is None and z.namelist() == [obj["name"] + ".tar.gz"]
        return h.unpack(z.read(z.namelist()[0]))


def contained(bs, js, root, src, hosted, physical):
    k = js(root + "/kernel.json")
    data = bs[root + "/all-process-opens.gz"]
    assert h.sha(data) == k["trace_sha256"] and k["code"] == 0
    sysroot = Path(physical)

    def resolved(path):
        path = Path(os.path.normpath(path))
        return (
            sysroot / path.relative_to(hosted) if path.is_relative_to(hosted) else path
        )

    driver = Path(k["driver"]["path"])
    assert driver.parent == sysroot / "lib" and k["driver"]["sha256"] == src
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        found = inspect(
            stream,
            lambda p: resolved(p) == sysroot / "bin/rustc",
            lambda p: resolved(p) == driver,
        )
    assert found == k["physical_compilers"]
    raw = gzip.decompress(data).splitlines()
    for a in k["compiler_argv"]:
        candidates = []
        for ln in raw:
            mat = re.match(rb'^(\d+) execve\("([^"]+)", ', ln)
            if (
                not mat
                or int(mat[1]) != a["pid"]
                or not ln.endswith(b"= 0")
                or resolved(Path(os.fsdecode(mat[2]))) != sysroot / "bin/rustc"
            ):
                continue
            got, end = json.JSONDecoder().raw_decode(os.fsdecode(ln[mat.end() :]))
            if (
                "--out-dir" in got
                and "--crate-name" in got
                and not any(v.startswith("--print") for v in got)
            ):
                candidates.append(got)
        assert candidates == [a["argv"]]
    assert sorted(
        (x["pid"], x["argv"][x["argv"].index("--crate-name") + 1])
        for x in k["compiler_argv"]
    ) == [(p, c) for p, c, _ in found]
    assert len({p for p, _, _ in found}) == len(found)
    typed = [J(v) for v in gzip.decompress(bs[root + "/stdout.gz"]).splitlines()]
    assert typed[-1] == {"reason": "build-finished", "success": True} and not any(
        v.get("message", {}).get("level") == "error" for v in typed
    )
    runs = []
    for pid, image, env in k["selected_script_environments"]:
        head = f'{pid} execve("{image}", '.encode()
        (actual,) = [v for v in raw if v.startswith(head) and v.endswith(b"= 0")]
        observed = [
            t.decode()
            for t in re.findall(
                rb'"((?:RUSTDOC|RUSTUP_HOME|RUSTUP_TOOLCHAIN)=[^"]*)"', actual
            )
        ]
        assert observed == env
        runs.append([pid, image, env])
    for pid, image in k["physical_wild"]:
        real = []
        for ln in raw:
            mat = re.match(rb'^(\d+) execve\("([^"]+)", ', ln)
            if not mat or int(mat[1]) != pid or not ln.endswith(b"= 0"):
                continue
            if (
                resolved(Path(os.fsdecode(mat[2])))
                != sysroot / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
            ):
                continue
            operands, _ = json.JSONDecoder().raw_decode(os.fsdecode(ln[mat.end() :]))
            real.append(operands[operands.index("-o") + 1])
        assert real == [image]
    return {
        "full": len(found),
        "wild": len(k["physical_wild"]),
        "crate": [c for _, c, _ in found],
        "build_scripts": runs,
    }


def controls(bs, js, row):
    enroll = js("enrollment.json")
    config = js("physical-layout.json")
    signed = js("signed-acquisition-strict.json")
    assert (
        enroll["source"] == h.SOURCES
        and enroll["run"] == str(RUN)
        and enroll["head"] == HEAD
        and enroll["cmd"] == CMD
        and enroll["row"] == row
    )
    assert (
        enroll["seal"] == old.SEAL == js("compiler-source-seal.json")
        and enroll["profile"] == old.CFG["1"]
    )
    home = Path(config["environment"]["HOME"])
    real = home / ".rustup/toolchains/ohm"
    assert config["physical_sdk"] == str(real) and config["environment"][
        "RUSTUP_HOME"
    ] == str(real.parents[1])
    assert (
        not (old.KEYS | {"RUSTUP_TOOLCHAIN", "RUSTC", "RUSTDOC"})
        & config["environment"].keys()
    )
    assert config["source_rustup"]["sha256"] == config["private_rustup"]["sha256"]
    for key in ("rustc", "rustdoc", "cargo"):
        p = config["proxies"][key]
        assert (
            p["sha256"] == config["private_rustup"]["sha256"]
            and p["node"] == config["private_rustup"]["node"]
        )
    pins = {}
    for i, change in enumerate(js("all-selections.json")):
        tag = change["record"]
        who = change["role"]
        assert tag == f"selection-{i}-{who}"
        spec = js(tag + "/selection.json")
        t = spec["tools"]
        assert t == change["tools"] and spec["role"] == who
        assert (
            spec["kit_files"] == 68
            and spec["tree"] == old.SEAL["roles"][old.NAMES[who]]["tree"]
        )
        assert t["cargo"]["sha256"] == h.FIXED and t["driver"]["sha256"] == old.SHA[who]
        pins_here = {
            k: (v["sha256"], v["dev_ino"], v["ctime_ns"]) for k, v in t.items()
        }
        assert pins.setdefault(who, pins_here) == pins_here
        real_opens = [
            s[1]
            for s in re.finditer(
                r'(?m)^.*?openat2?\([^"]*"([^"]*librustc_driver[^"]*)"[^\n]*\)\s+=\s*[0-9]+$',
                bs[tag + "/real-open.tsv"].decode(),
            )
        ]
        assert real_opens == spec["driver_opens"] and real_opens
    assert len(pins) == 2 and pins["C"]["driver"][1] != pins["P"]["driver"][1]
    first = enroll["order"][0]
    subjects = {}
    layout = {}
    refs = {}
    initial = Path(signed["environment"]["RUSTUP_HOME"]) / "toolchains/ohm"
    for lab, role, denial in (
        ("signed-arbitrary", "signed", False),
        ("source-arbitrary-" + first, first, True),
        ("source-supported-P", "P", False),
        ("source-supported-C", "C", False),
    ):
        path = "layout/" + lab
        state = js(path + "/layout.json")
        assert state["expected_denied"] == denial and state["RUSTDOC_explicit"] is None
        vals = state["markers"]
        names = {Path(k).name: v["bytes"] for k, v in vals.items()}
        assert names == (
            {
                ".ohm-worktree-seed-v7": "7\n",
                ".ohm-worktree-seed-deny-v7": "untrusted compile-time inputs\n",
            }
            if denial
            else {".ohm-worktree-seed-v7": "7\n"}
        )
        assert all(h.sha(v["bytes"].encode()) == v["sha256"] for v in vals.values())
        root = state["physical_sysroot"]
        assert state["sdk"] == root and state["own_sdk_has_rustdoc"] == (
            role == "signed"
        )
        supported = lab.startswith("source-supported")
        assert (root == str(real)) == supported
        crate = contained(
            bs,
            js,
            path,
            (signed["signed"]["driver"] if role == "signed" else old.SHA[role]),
            real if supported else initial,
            root,
        )
        assert sorted(crate["crate"]) == ["build_script_build", "native_layout_probe"]
        assert crate["build_scripts"] == [state["actual_script_env"]]
        layout[lab] = {
            "markers": names,
            "sysroot": root,
            "driver_opens": crate["full"],
            "wild": crate["wild"],
        }
    for role in "PC":
        name = old.NAMES[role]
        manifest = js("native-manifest-" + role + ".json")
        store = js("native-storage-" + role + ".json")
        assert (
            manifest["role"] == name
            and manifest["tree"] == old.SEAL["roles"][name]["tree"]
            and len(manifest["files"]) == 68 == store["files"]
        )
        assert (
            manifest["files"][store["driver"]][0] == old.SHA[role]
            and manifest["files"]["bin/cargo"][0] == h.FIXED
        )
        stride = {}
        for visit, n in (("cold", 17), ("repeat", 1), ("real-edit", None)):
            path = "real-driver-admission/" + role + "/" + visit
            stock = contained(bs, js, path, old.SHA[role], real, real)
            perf = js(path + "/observation.json")
            assert (
                not any("deny" in Path(k).name for k in perf["marker"])
                and sorted(perf["generated"]) == sorted(GEN)
                and perf["generated"] == GEN
            )
            assert stock["wild"] == 1 and (n is None or stock["full"] == n)
            if visit == "repeat":
                assert stock["crate"] == ["build_script_build"]
            if visit == "real-edit":
                assert (
                    "unicode_names2_generator" in stock["crate"]
                    and "build_script_build" in stock["crate"]
                )
            artifact = perf["generator"]
            out = gzip.decompress(bs["retained-ELF/" + artifact["sha256"] + ".gz"])
            assert out[:6] == b"\x7fELF\x02\x01" and h.sha(out) == artifact["sha256"]
            stride[visit] = {
                "full": stock["full"],
                "wild": stock["wild"],
                "crate": stock["crate"],
                "state": perf["source"],
                "hash": artifact["sha256"],
            }
        assert (
            stride["cold"]["hash"] == stride["repeat"]["hash"]
            and stride["real-edit"]["state"] != stride["cold"]["state"]
        )
        proof = js("effective-settings/" + role + "/checks.json")
        assert proof["stdout"] == "true true true\n" and f.codegen(
            proof["actual_scope"]
        ) == ("1", "on", "on")
        subjects[role] = {
            "SDK_allocated_B": store["archive_physical_B"],
            "driver": old.SHA[role],
            "visits": stride,
        }
        failures = []
        for branch, vis in (
            ("warm", ("ready", "invalid", "repair")),
            ("empty", ("invalid", "repair")),
        ):
            for ph in vis:
                path = "invalid-repair/" + role + "/" + branch + "/" + ph
                rows = [
                    J(v) for v in gzip.decompress(bs[path + "/stdout.gz"]).splitlines()
                ]
                meta = js(path + "/source.json")
                assert rows[-1] == {
                    "reason": "build-finished",
                    "success": ph != "invalid",
                } and meta["cargo_exit"] == (101 if ph == "invalid" else 0)
                errors = [
                    r["message"]
                    for r in rows
                    if r.get("message", {}).get("level") == "error"
                ]
                assert errors == meta["errors"] and len(errors) == int(ph == "invalid")
                if errors:
                    e = errors[0]
                    assert e["code"]["code"] == "E0308" and any(
                        sp["is_primary"]
                        and sp["file_name"] == SUBPATH
                        and "OHM_LINKED_RUST_E0308"
                        in "".join(t["text"] for t in sp["text"])
                        for sp in e["spans"]
                    )
                    failures.append(e)
                else:
                    r = js(path + "/returned.json")
                    assert r["verdict"] == EXPECTED and r["generated"] == GEN
                    image = r["reader"]["sha256"]
                    assert (
                        h.sha(gzip.decompress(bs["retained-ELF/" + image + ".gz"]))
                        == image
                    )
                    assert refs.setdefault(role, image) == image
        assert len(failures) == 2 and failures[0] == failures[1]
    for kind, digest in GEN.items():
        assert h.sha(gzip.decompress(bs["generated/" + digest + ".gz"])) == digest
    return layout, subjects, refs


def audit(bs, row):
    js = lambda n: J(bs[n])
    assert "complete.json" in bs and "safety-admission.json" in bs
    calibrations = f.calibration(bs)
    layout, subjects, refs = controls(bs, js, row)
    paired = js("paired-instructions.json")
    prs = js("component.json")
    components = {}
    core = {}
    coarse = {}
    for r in "PC":
        for state in ("old", "new"):
            src = prs["generator_elf"][r][state]
            real = gzip.decompress(bs["retained-ELF/" + src + ".gz"])
            assert h.sha(real) == src
            counts = []
            for i in (0, 1):
                p = "component/" + r + "/" + state + "/" + str(i)
                rec = js(p + "/result.json")
                a = js(p + "/whole.json")
                assert (
                    rec["generated"] == GEN
                    and rec["elf"]["sha256"] == src
                    and rec["argv"][-1] == rec["elf"]["path"]
                    and a["code"] == 0
                )
                counts.append(
                    h.hw(a)
                    if a["event_errno"] == 0
                    and a["enabled"] == a["running"]
                    and a["instructions"] > 0
                    else None
                )
            assert counts == prs["component_counts"][r][state]
            components.setdefault(state, {})[r] = counts
    # The signed proof reader accepts an arbitrary layout prefix. This dict contains aliases of the same byte objects.
    remap = dict(bs)
    remap.update(
        {
            "linked-supported/" + n[len("ordinary-lib/") :]: v
            for n, v in bs.items()
            if n.startswith("ordinary-lib/")
        }
    )
    for i, r in enumerate("PC"):
        d = "ordinary-lib/opt" + str(i)
        info = f.linked(remap, "supported", "B", i)
        sel = js(d + "/runtime.json")
        first, final = js("enrollment.json")["states"]
        for phase in (
            "cold",
            "neutral-unchanged",
            "historical-hunk",
            "first-unchanged",
            "traced-repeat",
            "independent-empty",
        ):
            state = first if phase in ("cold", "neutral-unchanged") else final
            assert info[phase]["generator_elf"] == prs["generator_elf"][r][state]
        for label, roster in (
            ("traced-repeat", "build-repeat"),
            ("independent-empty", "build-cold"),
        ):
            native(bs, d + "/" + label, sel["tools"], "B", roster)
        returned = js(d + "/qualified-readers.json")
        assert returned["independent-empty"]["reader"] == refs[r] and len(returned) == 6
        core[r] = {
            w: {
                "instructions": s["instructions"],
                "allocated_B": s["allocated_B"],
                "source": s["source"],
                "regions": s["regions"],
            }
            for w, s in info.items()
            if "instructions" in s
        }
        core[r]["edit-plus-repeat"] = {
            "instructions": core[r]["historical-hunk"]["instructions"]
            + core[r]["first-unchanged"]["instructions"],
            "allocated_B": core[r]["first-unchanged"]["allocated_B"],
        }
    for phase in core["P"]:
        p = core["P"][phase]
        c = core["C"][phase]
        v = paired["complete_whole_Cargo"][phase]
        assert (p["instructions"], c["instructions"]) == (
            v["parent_instructions"],
            v["candidate_instructions"],
        )
        assert (p["allocated_B"], c["allocated_B"]) == (
            v["parent_fresh_store_allocated_B"],
            v["candidate_fresh_store_allocated_B"],
        )
        assert p["instructions"] / c["instructions"] == v["parent_over_candidate"]
        coarse[phase] = v
    edge = h.providers(bs, js)
    return {
        "host": js("enrollment.json")["host"],
        "row": row,
        "reopened_calibrations": len(calibrations) * 4,
        "layout": layout,
        "source_roles": subjects,
        "own_empty_ELF_and_repair": refs,
        "component": components,
        "provider": edge,
        "endpoints": coarse,
        "whole": core,
    }
