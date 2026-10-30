"""Independently recount the untimed source qualification and inventory its native products."""
import argparse
import ast
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from elf import compare, describe, digest
from rebuild import CARGO_HASH, CARGO_SOURCE, MEMBERS, SCRIPTS, patched_record, rt
sys.path.insert(0, str(SCRIPTS / "ohm-gnu-ty-input-census"))
import cli


API = "repos/astral-experiments/ohm/actions/"
GH = os.environ.get("GH_BIN") or shutil.which("gh-auto") or shutil.which("gh")
EXEC = re.compile(rb'^execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:NULL|0x[^)]*)\)\s+= 0$')


def get(endpoint):
    return json.loads(subprocess.check_output([GH, "api", API + endpoint]))


@contextmanager
def archive(asset):
    assert not asset["expired"]
    with os.fdopen(os.memfd_create("source-qualification-zip"), "w+b") as scratch:
        subprocess.run([GH, "api", API + f'artifacts/{asset["id"]}/zip'], stdout=scratch, check=True)
        assert scratch.tell() == asset["size_in_bytes"]
        scratch.seek(0)
        assert "sha256:" + hashlib.file_digest(scratch, "sha256").hexdigest() == asset["digest"]
        scratch.seek(0)
        with zipfile.ZipFile(scratch) as z:
            yield z


def events(raw):
    """Read successful kernel execs from every actual PID, independent of the runner summary."""
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as t:
        for file in t.getmembers():
            if not file.isreg():
                continue
            assert re.fullmatch(r"(?:trace/)?proc\.\d+", file.name), file.name
            for line in t.extractfile(file).read().splitlines():
                if not (line.endswith(b"= 0") and line.startswith((b"execve(", b"execveat("))):
                    continue
                matched = EXEC.fullmatch(line)
                assert matched, line[:200]
                name = ast.literal_eval(matched[1].decode())
                if Path(name).name in ("rustc", "cargo", "ld", "ld.bfd", "rust-lld", "ld.lld", "wild"):
                    yield name, ast.literal_eval(matched[2].decode())


def json_at(z, path):
    return json.loads(z.read(path))


def sdk(z, role, selection):
    prefix = "ohm-aarch64-linux-zmij/receipts/"
    physical = json_at(z, prefix + "physical-sdk.json")
    source = json_at(z, prefix + "selected.json")
    rows = MEMBERS["common"] | {MEMBERS["driver_path"]: selection["driver"]}
    if role == "builder":
        rows["bin/cargo"] = [rt.TOOLS["bin/cargo"], source["cargo"][1], 0o755]
    assert physical == {"differences": {}, "files": rows} and len(rows) == source["member_count"] == 119
    assert (source["role"], source["commit"], source["tree"], source["bootstrap"]) == (
        role, selection["source"], selection["tree"], selection["bootstrap"])
    actual = source | {"manifest_sha256": digest(z.read(prefix + "physical-sdk.json"))}
    if role == "builder":
        compiler = json_at(z, prefix + "P-sdk.json")
        assert len(compiler["files"]) == 117 and set(rows) - set(compiler["files"]) == set(rt.TOOLS)
        assert all(compiler["files"][n] == rows[n] for n in compiler["files"])
        complete = compiler | {"files": rows}
        published = digest((json.dumps(complete, sort_keys=True, indent=2) + "\n").encode())
        assert published == "325d6e037d50d7b15415961dba0f71caca127063292b5adabc5a292388c7a670"
        actual["original_complete_builder_manifest"] = published
    return actual


def cargo(z, producer, run_head):
    prefix = "gnu-cargo293-build/receipts/"
    original = json_at(z, prefix + "physical-cargo.json")
    assert original["source"]["source"] == CARGO_SOURCE and original["rebuilt"] == original["measured"] == CARGO_HASH
    assert producer == original["product"] == json_at(z, prefix + "cargo-293-source/verified.json")
    assert producer["git"] == CARGO_SOURCE and producer["cargo_sha256"] == CARGO_HASH
    assert producer["source_workflow"] == run_head and producer["builder"] == rt.TOOLS["bin/cargo"]
    assert producer["SDK_driver"] == MEMBERS["roles"]["N"]["driver"][0]
    native = rt.load(SCRIPTS / "ohm-aarch64-versioned/qualified-builds.json")
    assert original["source_date_epoch"] == 1793374538 and producer["typed_units"] == native["typed"]
    raw = z.read(prefix + "cargo-293-source/native-exec.tar.gz")
    assert digest(raw) == producer["native_trace"]
    roots = []
    for path, args in events(raw):
        if path.endswith("gnu-cargo293-build/rustup/toolchains/ohm/bin/rustc") and "--crate-name" in args:
            if args[args.index("--crate-name") + 1] == "cargo":
                roots.append(args)
    assert sorted(roots) == sorted(producer["compiler_root_argv"]) == sorted(native["root_compilers"])
    stdout = gzip.decompress(z.read(prefix + "cargo-293-source/marker-unit/stdout.gz"))
    assert b"1 passed; 0 failed;" in stdout and b"recheck_links_only_for_the_compiler_generated_marker ... ok" in stdout
    result = {"source": CARGO_SOURCE, "elf": original["rebuilt"], "source_date_epoch": original["source_date_epoch"],
              "typed_units": native["typed"], "root_native_commands": len(roots), "marker_unit": "passed"}
    clock = prefix + "clock-control/"
    if clock + "comparison.json" in z.namelist():
        pinned, unfixed = (subprocess.check_output(["zstd", "-qdc"], input=z.read(clock + name + "-cargo.zst"))
                            for name in ("pinned", "unpinned"))
        assert describe(pinned) == rt.load(HERE / "original-cargo-elf.json")["elf"]
        differences = compare(pinned, unfixed)
        assert differences == json_at(z, clock + "comparison.json")
        before, after = describe(pinned), describe(unfixed)
        assert after == json_at(z, "gnu-cargo-clock-control/receipts/cargo-elf.json")
        counts = {}
        for name in differences["changed_sections"]:
            a, b = before["sections"][name], after["sections"][name]
            assert (a["type"], a["size"], a["offset"]) == (b["type"], b["size"], b["offset"])
            region = slice(a["offset"], a["offset"] + a["size"])
            counts[name] = sum(x != y for x, y in zip(pinned[region], unfixed[region]))
        result["clock_control"] = differences
        result["clock_control_changed_section_bytes"] = counts
    return result


def ruff(z, role):
    root = "observed-ruff/receipts/"
    enrolled = json_at(z, root + "enrolled.json")
    terminal = json_at(z, root + "terminal.json")
    assert enrolled["cli"] == cli.CLI and enrolled["trees"] == cli.TREES and enrolled["lock_sha256"] == cli.LOCK
    assert enrolled["cargo_sha"] == CARGO_HASH and terminal["untimed"]
    summary = terminal["phases"]
    outputs = {}
    rosters = set()
    for phase in ("cold", "edit", "repeat", "invalid", "repair", "empty-new"):
        base = root + phase + "/"
        stdout, stderr = (gzip.decompress(z.read(base + s + ".gz")) for s in ("stdout", "stderr"))
        command = json_at(z, base + "command.json")
        assert (digest(stdout), digest(stderr)) == (command["stdout"], command["stderr"])
        assert command["argv"][-len(cli.CLI):] == cli.CLI
        rows = list(map(json.loads, stdout.splitlines()))
        assert rows[-1] == {"reason": "build-finished", "success": phase != "invalid"}
        if phase == "invalid":
            assert command["exit"] == 101 and summary[phase] == {"diagnostic":"E0425"}
            assert any((m.get("message", {}).get("code") or {}).get("code") == "E0425" and
                       "OHM_RUFF_PLE0643_INVALID_EDIT" in m["message"]["rendered"] for m in rows)
            outputs[phase] = {"error": "E0425"}
            continue
        assert command["exit"] == 0
        units = [m for m in rows if m["reason"] == "compiler-artifact"]
        assert len(units) == 372
        roster = sorted(json.dumps([m[k] for k in ("target", "package_id", "features", "profile")], sort_keys=True)
                        for m in units)
        rosters.add(digest(json.dumps(roster).encode()))
        native = json_at(z, base + "census.json")["product"]
        assert native == summary[phase]["product"]
        for name, (input, old, new) in cli.PROBES.items():
            call = json_at(z, base + name + "-cmd.json")
            payload = json.loads(gzip.decompress(z.read(base + name + "-stdout.gz")))
            verdict = [(m["code"], m["location"]["row"]) for m in payload]
            assert call["source"].encode() == input and call["argv"][0] == "qemu-aarch64"
            assert verdict == (old if phase == "cold" else new) and call["exit"] == int(bool(verdict))
            assert gzip.decompress(z.read(base + name + "-stderr.gz")) == b""
        outputs[phase] = {"elf": native["sha256"], "text": native["text_sha"], "elf_bytes": native["bytes"]}
        if phase not in ("edit", "repeat"):
            continue
        full, link_only, linked = [], [], []
        for path, argv in events(z.read(base + "execs.tar.gz")):
            if (path.endswith("/rustup/toolchains/ohm/bin/rustc") and "--crate-name" in argv
                    and any(a == "--emit" or a.startswith("--emit=") for a in argv)):
                bucket = link_only if any(a.startswith("-Zlink-only") or a == "link-only" for a in argv) else full
                bucket.append(argv[argv.index("--crate-name") + 1])
            if Path(path).name in ("ld", "ld.bfd", "rust-lld", "ld.lld", "wild") and "-o" in argv:
                linked.append((path, Path(argv[argv.index("-o") + 1]).name))
        assert sorted(full) == sorted(summary[phase]["full"]) and sorted(link_only) == sorted(summary[phase]["link_only"])
        expected = 19 if role == "parent" else {"edit": 4, "repeat": 3}[phase]
        assert len(full) == expected and link_only == ([] if role == "parent" else ["ruff"])
        assert sorted(product for _, product in linked) == ["build_script_build", "ruff"]
        assert any("aarch64-linux-gnu/bin/ld" in linker and product == "ruff" for linker, product in linked)
        assert summary[phase]["root_links"] == 1
        outputs[phase]["full_rustc"] = sorted(full)
        outputs[phase]["link_only_rustc"] = link_only
        outputs[phase]["native_link_outputs"] = sorted(product for _, product in linked)
    assert len(rosters) == 1 and outputs["cold"]["elf"] != outputs["empty-new"]["elf"]
    for phase in ("edit", "repeat", "repair"):
        assert outputs[phase]["elf"] == outputs["empty-new"]["elf"]
        assert outputs[phase]["text"] == outputs["empty-new"]["text"]
    return {"roster": rosters.pop(), "units": 372, "phases": outputs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=int)
    parser.add_argument("head")
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    run = get(f"runs/{args.run}")
    assert (run["id"], run["head_sha"], run["head_branch"], run["path"], run["event"], run["conclusion"]) == (
        args.run, args.head, "charlie/qa-gnu-svc-source-rebuild", ".github/workflows/ci.yml", "workflow_dispatch", "success")
    all_assets = get(f"runs/{args.run}/artifacts?per_page=100")["artifacts"]
    assets = {a["name"]:a for a in all_assets}
    assert set(assets) == {"source-built-cargo", "source-build-builder", "source-build-parent", "source-build-patched"}
    assert len(assets) == len(all_assets)
    for a in assets.values():
        assert (a["workflow_run"]["id"], a["workflow_run"]["head_sha"]) == (args.run, args.head)
    result = {"run": args.run, "qa": args.head, "archives": {
        n:{"id":a["id"], "bytes":a["size_in_bytes"], "sha256":a["digest"]} for n,a in assets.items()}}
    with archive(assets["source-built-cargo"]) as z:
        assert set(z.namelist()) == {"cargo.zst", "product.json"}
        producer = json_at(z, "product.json")
        elf = describe(subprocess.check_output(["zstd", "-qdc"], input=z.read("cargo.zst")))
        assert elf == rt.load(HERE / "original-cargo-elf.json")["elf"]
    with archive(assets["source-build-builder"]) as z:
        result["builder"] = sdk(z, "builder", MEMBERS["roles"]["N"])
        result["cargo"] = cargo(z, producer, args.head)
    for role, selected in (("parent", MEMBERS["roles"]["M"]), ("patched", patched_record())):
        with archive(assets["source-build-" + role]) as z:
            result[role] = {"SDK":sdk(z, role, selected), "ruff":ruff(z, role)}
    assert result["parent"]["ruff"]["roster"] == result["patched"]["ruff"]["roster"]
    for step in ("cold", "edit", "repeat", "repair", "empty-new"):
        assert result["parent"]["ruff"]["phases"][step]["text"] == result["patched"]["ruff"]["phases"][step]["text"]
    args.result.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("Verified all three 119-file SDK manifests, the complete Cargo ELF, native compiler and linker counts, clean outputs and QEMU verdicts.")


if __name__ == "__main__":
    main()
