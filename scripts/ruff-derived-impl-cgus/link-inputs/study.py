"""Off-clock comparison of actual linker inputs on one real fixed-HEAD test build."""

import gzip
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "norun")]
import fixed_head as h
from objects import digest, require
from on_link import encode
from option_probe import probe

q, b, p, s = h.q, h.b, h.p, h.s
OUT = q.OUT
SPEC = json.loads((HERE / "registered.json").read_bytes())
PRIVATE = OUT.parent / "native-link-private"
NAMES = PRIVATE / "registered-output-names"


def snapshots(dst):
    report = {}
    for top in (b.TARGET, b.BUILD):
        for filename in top.rglob("*"):
            if not filename.is_file() or filename.is_symlink():
                continue
            relative = filename.relative_to(top)
            # Cargo's split workspace paths and older public fingerprints use different layouts.
            fields = relative.parts
            workspace = any(
                k == "ruff" and re.fullmatch(r"[0-9a-f]{16}", n)
                for k, n in itertools.pairwise(fields)
            )
            older = any(
                k == ".fingerprint" and re.fullmatch(r"ruff-[0-9a-f]{16}", n)
                for k, n in itertools.pairwise(fields)
            )
            name = filename.name
            rustdep = name.endswith(".d") and (
                name.startswith(
                    (
                        "ruff-",
                        "config-",
                        "analyze_graph-",
                        "cli-",
                        "direxist_guard-",
                        "integration_test-",
                        "resolve_files-",
                    )
                )
                or name == "ruff.d"
            )
            relevant = (workspace or older) and (
                bool({"fingerprint", ".fingerprint"} & set(fields))
                or "unused-extern" in name
                or "relink" in name
                and name.endswith(".json")
                or name.endswith(".d")
                or name in {"manifest.json", "dep-info"}
            )
            if not (rustdep or relevant):
                continue
            key = "/".join([top.name, *relative.parts])
            length = filename.stat().st_size
            obj = {"name": name, "bytes": length, "sha256": digest(filename)}
            if length <= 2 << 20:
                f = dst / "record-bodies" / (obj["sha256"] + ".gz")
                if not f.is_file():
                    f.parent.mkdir(exist_ok=True)
                    f.write_bytes(
                        gzip.compress(filename.read_bytes(), compresslevel=3, mtime=0)
                    )
                obj["raw"] = f.name
            report[key] = obj
    encode(dst / "fingerprints.json.gz", report)


def phase(label, state, observed=False, cargo_log=False):
    before = s.validate(b.WORK, state)
    td = b.PUB / label
    td.mkdir()
    cmd = list(q.CMD)
    e = b.env()
    if cargo_log:
        e = e | {
            "CARGO_LOG": "cargo::compiler=info,cargo::compiler::fingerprint=trace,cargo::core::compiler=info,cargo::core::compiler::fingerprint=trace"
        }
    b.need(
        not set(e)
        & {
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST",
            "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST",
            "RUSTFLAGS",
            "LD_PRELOAD",
            "RUSTC_WRAPPER",
        },
        "unexpected Cargo environment",
    )
    if observed:
        private = PRIVATE / label
        private.mkdir()
        public = b.PUB / "link-inputs" / label
        public.mkdir(parents=True)
        b.put(
            private / "policy.json",
            {
                "target": str(b.TARGET),
                "roots": list(
                    map(
                        str,
                        [
                            b.ROOT,
                            b.WORK,
                            Path("/usr"),
                            Path("/lib"),
                            Path("/lib64"),
                            Path("/etc/ld.so.cache"),
                            Path("/etc/localtime"),
                            Path("/etc/locale.alias"),
                        ],
                    )
                ),
                "native_shadow_target": (
                    next(
                        k for k, v in SPEC["outputs"].items() if v == "tests/config.rs"
                    )
                    if state == s.NEW
                    else None
                ),
            },
        )
        cmd = [
            PRIVATE / "observer",
            private,
            public,
            NAMES,
            b.SDK / b.WILD,
            HERE / "on_link.py",
            *cmd,
        ]
    with (td / "stdout").open("xb") as so, (td / "stderr").open("xb") as se:
        output = subprocess.run(
            cmd, cwd=b.WORK, env=e, stdout=so, stderr=se, check=False
        )
    require(
        output.returncode == 0,
        (
            label,
            "ordinary compile",
            output.returncode,
            (td / "stderr").read_text(errors="replace")[-1200:],
        ),
    )
    require(before == s.validate(b.WORK, state), "source changed in Cargo command")
    b.put(td / "source.json", before)
    b.put(td / "ruff-build-script.json", h.build_script())
    verdict = q.verdicts(td, state)
    if observed or cargo_log:
        snapshots(td)
    return verdict


def returned(label, actual):
    records = {}
    public = b.PUB / "link-inputs" / label
    for stem, kind in SPEC["outputs"].items():
        status = public / ("readback-" + stem + ".status")
        data = {"status": status.read_text().strip() if status.is_file() else "missing"}
        receipt = public / stem / "receipt.json"
        if receipt.is_file():
            native = actual["cli"] if kind == "CLI" else actual["roots"][kind]
            r = json.loads(receipt.read_bytes())
            data["genuine_sha256"] = native["sha256"]
            data["independent_sha256"] = r["standalone"]["sha256"]
            data["same"] = r["standalone"] == {
                "bytes": native["bytes"],
                "sha256": native["sha256"],
            }
        records[kind] = data
    b.put(b.PUB / (label + "-readback-status.json"), records)
    return all(row["status"] == "1 0" and row.get("same") for row in records.values())


def main():
    b.need(
        os.environ["GITHUB_REF_NAME"]
        == "charlie/qa-ruff-28392-native-link-inputs-20261104"
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
        and b.git("rev-parse", "HEAD") == s.NEW
        and b.git("rev-parse", "HEAD^") == s.OLD,
        "unregistered worker or Ruff checkout",
    )
    require(
        SPEC["ordinary"] == q.CMD
        and {s.OLD, s.NEW} == set(SPEC["sources"])
        and set(SPEC["outputs"].values()) == set(q.ROOTS) | {"CLI"},
        "source/argv/test admission",
    )
    OUT.mkdir()
    b.PUB = OUT / "C"
    b.PUB.mkdir()
    PRIVATE.mkdir(mode=0o700)
    b.ROOT.mkdir()
    b.guard()
    b.put(
        OUT / "registration.json",
        {
            "plan": SPEC,
            "head": os.environ["GITHUB_SHA"],
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "runner": os.uname().machine,
            "sources": {
                k.name: digest(k)
                for k in [
                    *HERE.glob("*.py"),
                    HERE / "observe.c",
                    HERE / "registered.json",
                ]
            },
        },
    )
    sdk, compiled = q.trained.fetch("C", q.CACHE, b.PUB / "factory")
    q.trained.transport.install(sdk, compiled, b.SDK, b.RUSTUP / "toolchains/ohm")
    for name in ("rustc", "cargo"):
        require(
            subprocess.check_output([name, "+ohm", "-vV"], env=b.env(), text=True)
            == compiled["versions"][name],
            "wrong physical toolchain",
        )
    require(
        SPEC["candidate"] in compiled["versions"]["rustc"]
        and SPEC["cargo"] in compiled["versions"]["cargo"]
        and digest(b.SDK / b.WILD) == SPEC["wild"],
        "release source/actual ld discrepancy",
    )
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            HERE / "observe.c",
            "-o",
            PRIVATE / "observer",
        ],
        check=True,
    )
    NAMES.write_text("\n".join(sorted(SPEC["outputs"])) + "\n")
    b.verdict = h.version
    native_rejections = {}

    def same(expected, received, why):
        if expected != received:
            different = [
                name
                for name, value in expected["roots"].items()
                if value != received["roots"][name]
            ]
            native_rejections[why] = {
                "roots": different,
                "cli": expected["cli"] == received["cli"],
                "verdict": expected["verdict"] == received["verdict"],
            }
            b.put(b.PUB / "native-rejections.json", native_rejections)

    b.select(s.OLD)
    saved = PRIVATE / "old-checkout"
    proof = p.old_namespace.save_checkout(b.WORK, saved)
    b.put(b.PUB / "old-source.json", s.validate(b.WORK, s.OLD, full=True))
    b.prepare()
    b.put(
        b.PUB / "signed-effective-options.json",
        probe(PRIVATE / "private-subcommand", b.WORK, b.env()),
    )
    old = phase("ordinary-old", s.OLD)
    same(old, phase("ordinary-old-unchanged", s.OLD), "settled OLD")
    initial = h.build_script()
    b.put(b.PUB / "edited-buffers.json", s.apply(b.WORK))
    edit = phase("ordinary-edit", s.NEW)
    same(edit, phase("ordinary-new-unchanged", s.NEW), "settled real working-tree edit")
    require(h.build_script() == initial, "ordinary edit reran original build script")
    q.invalid()
    same(edit, phase("ordinary-repair", s.NEW), "repair")
    p.empty_outputs()
    b.prepare()
    same(edit, phase("ordinary-empty-new", s.NEW), "fully empty native receiver")

    def native(row):
        return {k: v["sha256"] for k, v in row["roots"].items()} | {
            "CLI": row["cli"]["sha256"]
        }

    settled = [k for k, h0 in native(old).items() if native(edit)[k] == h0]
    require(
        sorted(settled) == sorted(SPEC["expected_unchanged"]),
        ("different real output class", settled),
    )
    p.empty_outputs()
    p.old_namespace.restore_checkout(b.WORK, saved, proof)
    b.prepare()
    physical_old = phase("observed-old", s.OLD, observed=True)
    same(old, physical_old, "observed OLD")
    same(old, phase("observed-old-unchanged", s.OLD), "observed settled OLD")
    initial = h.build_script()
    b.put(b.PUB / "observed-edit-buffers.json", s.apply(b.WORK))
    physical_new = phase("observed-edit", s.NEW, observed=True)
    same(edit, physical_new, "observed edit")
    same(edit, phase("observed-new-unchanged", s.NEW), "observed settled NEW")
    require(h.build_script() == initial, "observed edit reran original build script")
    finished = [
        returned(name, value)
        for name, value in [
            ("observed-old", physical_old),
            ("observed-edit", physical_new),
        ]
    ]
    # This separate history fixes Cargo's own logging environment before the clean baseline.
    # The actual link-input observation above always used the original sanitized Cargo environment.
    p.empty_outputs()
    p.old_namespace.restore_checkout(b.WORK, saved, proof)
    b.prepare()
    same(old, phase("logged-old", s.OLD, cargo_log=True), "logged baseline")
    same(old, phase("logged-old-unchanged", s.OLD, cargo_log=True), "logged settled")
    b.put(b.PUB / "logged-edit-buffers.json", s.apply(b.WORK))
    same(edit, phase("logged-edit", s.NEW, cargo_log=True), "logged working edit")
    same(
        edit,
        phase("logged-new-unchanged", s.NEW, cargo_log=True),
        "logged settled edit",
    )
    b.put(
        b.PUB / "reach.json",
        {
            "genuine": True,
            "old": native(old),
            "edit": native(edit),
            "unchanged": sorted(settled),
            "same_source": s.validate(b.WORK, s.NEW, full=True),
            "all_independent_native_inputs": all(finished),
        },
    )
    require(
        all(finished) and not native_rejections,
        "one or more physical or native oracles refused; retain observations",
    )
    p.empty_outputs()
    require(
        PRIVATE.name == "native-link-private"
        and PRIVATE.parent == OUT.parent
        and not PRIVATE.is_symlink(),
        "private scope",
    )
    shutil.rmtree(PRIVATE)


if __name__ == "__main__":
    main()
