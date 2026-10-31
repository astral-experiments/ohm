"""Use local read-only object stores and native receipts to exercise the QA protocol without building Ruff."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chunks
import observe
import state as s
from kits import ENROLL, need, sha, write


def run(ruff, native, record):
    with tempfile.TemporaryDirectory(prefix="mixed-ruff-preflight-") as tmp:
        root = Path(tmp)
        (root / "slot/tmp").mkdir(parents=True)
        (root / "receipts").mkdir()
        src = root / "ruff"
        src.mkdir()

        def git(*args):
            return subprocess.check_output(["git", "-C", src, *args]).decode().strip()

        keys = (
            set(ENROLL["e2e"]["original"]) | set(ENROLL["migration"]["original"]) | {s.BAD_PATH, "Cargo.lock"}
        )
        common = Path(
            subprocess.check_output(
                ["git", "-C", ruff, "rev-parse", "--path-format=absolute", "--git-path", "objects"], text=True
            ).strip()
        )
        git("init", "-q", "--template=")
        (src / ".git/objects/info").mkdir(exist_ok=True)
        (src / ".git/objects/info/alternates").write_text(str(common) + "\n")
        git("config", "core.sparseCheckout", "true")
        git("config", "core.sparseCheckoutCone", "false")
        (src / ".git/info").mkdir(exist_ok=True)
        (src / ".git/info/sparse-checkout").write_text("".join("/" + k + "\n" for k in sorted(keys)))
        git("checkout", "--quiet", "--detach", ENROLL["source"])
        s.prime_patches(root)
        cases = {}
        for kind, modes in [
            ("e2e", ["original", "reversed", "reversed", "original", "original"]),
            ("migration", ["original", "reversed", "invalid", "reversed", "reversed", "original"]),
        ]:
            rows = []
            previous = None
            for mode in modes:
                s.state(root, kind, mode)
                r = {
                    k: [sha(src / k), (src / k).stat().st_mtime_ns] if (src / k).is_file() else None
                    for k in keys
                }
                if rows and mode == previous:
                    need(rows[-1]["files"] == r, "unchanged source was touched")
                rows.append({"mode": mode, "files": r})
                previous = mode
            need(
                not git("status", "--porcelain=v1", "--untracked-files=normal"),
                "did not restore pristine Ruff",
            )
            cases[kind] = {
                "modes": modes,
                "original": ENROLL["tree"],
                "reverse": ENROLL[kind]["reverse_tree"],
                "untouched_repeat": True,
            }
        epochs = set()
        members = 0
        with zipfile.ZipFile(native) as z:
            for n in z.namelist():
                if not n.endswith("libsubject.rmeta"):
                    continue
                p = root / "foreign.rmeta"
                p.write_bytes(z.read(n))
                epochs.add(observe.metadata_stamp(p))
                members += 1
        need(
            epochs == {"rustc 1.99.0-dev (Ohm metadata 1)", "rustc 1.99.0-dev (Ohm metadata 2)"},
            "failed to distinguish actual metadata epochs",
        )
        (root / "slot/target").mkdir()
        (root / "slot/shared").mkdir()
        a = root / "slot/target/one"
        a.write_bytes(b"x" * 12732)
        b = root / "slot/shared/the-same-inode"
        os.link(a, b)
        p = root / "receipts/allocation"
        p.mkdir()
        allocation = s.storage(root, p)
        need(
            allocation["paths"] == 4 and allocation["unique_inodes"] == 3,
            "cross-root hardlinks double-counted",
        )
        absent = chunks.capture(root, "pre-install")
        need(
            absent["eligible_sessions"] == 0 and not absent["selected"],
            "empty incremental store produced samples",
        )
        prefix = root / "slot/target/ty_python_semantic-control"
        block = chunks.BLOCK
        for session, data in (
            ("s-a", b"A" * block * 2 + b"tail!"),
            ("s-b", b"A" * block + b"B" * block + b"tail!"),
            ("s-c-working", b"Z" * block * 4),
        ):
            for name in chunks.FILES:
                f = prefix / session / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
        alias = root / "slot/shared/ty_python_semantic-control/s-alias"
        alias.mkdir(parents=True)
        for name in chunks.FILES:
            os.link(prefix / "s-a" / name, alias / name)
        for label in ("pre-install", "post-first", "post-repair"):
            chunks.capture(root, label)
        survey = chunks.summarize(root / "receipts/semantic-chunks")
        sample = survey["intra"]["pre-install"]
        need(
            sample["eligible_sessions"] == 2 and len(survey["across"]["post-first"]) == 4,
            "duplicate/working incremental sessions entered comparison",
        )
        for f in sample["distinct_sessions"].values():
            need(
                f["common_unique_complete_block_bytes"] == block
                and f["common_unique_partial_block_bytes"] == 5
                and f["common_bytes_including_multiplicity"] == block + 5
                and not f["same_inode"],
                "incorrect fixed-chunk overlap",
            )
        compiler = (
            Path(subprocess.check_output(["rustc", "+ohm", "--print", "sysroot"], text=True).strip())
            / "bin/rustc"
        )
        native_elf = observe.elf(root, compiler)
        need(native_elf["sha256"] == sha(compiler), "native ELF index changed")
        write(
            record,
            {
                "source": ENROLL["source"],
                "source_states": cases,
                "native_run": ENROLL["native_run"],
                "actual_foreign_headers": members,
                "epochs": sorted(epochs),
                "cross_root_hardlink_paths": allocation["paths"],
                "cross_root_unique_inodes": allocation["unique_inodes"],
                "native_elf_sha256": native_elf["sha256"],
                "incremental_chunks": {
                    "complete_common": block,
                    "partial_common": 5,
                    "eligible_sessions": 2,
                    "hardlink_alias_ignored": True,
                    "absent_before_creation": True,
                },
                "protocol_only": True,
            },
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ruff", type=Path)
    p.add_argument("native_admission_zip", type=Path)
    p.add_argument("record", type=Path)
    a = p.parse_args()
    run(a.ruff.resolve(), a.native_admission_zip, a.record)
