"""Read only the admitted two-mirror pilot and classify each real AST codegen edge."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument("reader", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    admission = json.loads(args.receipt.read_bytes())
    assert admission["run"] == 41086895982 and admission["QA"] == "75a96d2298549ab1ad642b9c7c1862562a7bd81a"
    files = admission["immutable_artifacts"]
    reader = runpy.run_path(os.fspath(args.reader))
    target = args.output
    target.mkdir()
    subjects = {}
    for number in ("01", "02"):
        name = "gnu-versioned-pilot-" + number
        artifact_id, size, want = files[name]
        endpoint = "repos/astral-experiments/ohm/actions/artifacts/" + str(artifact_id)
        remote = json.loads(subprocess.check_output(["gh", "api", endpoint]))
        assert (remote["digest"], remote["size_in_bytes"]) == ("sha256:" + want, size)
        assert not remote["expired"] and (remote["workflow_run"]["id"], remote["workflow_run"]["head_sha"]) == (admission["run"], admission["QA"])
        assert shutil.disk_usage(target).free > size + 16 * 2**30
        archive = target / (number + ".zip")
        with archive.open("xb") as f:
            subprocess.run(["gh", "api", endpoint + "/zip"], stdout=f, check=True)
        with archive.open("rb") as f:
            assert hashlib.file_digest(f, "sha256").hexdigest() == want and archive.stat().st_size == size
        with zipfile.ZipFile(archive) as z:
            term = json.loads(z.read("terminal.json"))
            assert term["block"] == number and term["sources"]["M"] == "8f42a1c11e66c2a55299914d5025e4fa7549ead4"
            cells = {}
            for role in "ANM":
                root = f"block-{number}-{role}-edit-cycle/first-real-edit"
                result = reader["size"](z, root)
                native = json.loads(z.read(root + "/verified.json"))["processes"]["ruff_python_ast"]
                assert native["profile"] == result["raw_profile"] and native["Ir"] == result["AST_Ir"]
                cells[role] = result
            subjects[number] = {"artifact_sha256": want, "roles": cells}
        archive.unlink()
    payload = {
        "source": admission["QA"], "run": admission["run"], "paired_score_receipt_sha256": admission["analysis"],
        "method": "Actual calls to rustc_codegen_llvm::base::compile_codegen_unit and its module_codegen child in each root compiler profile. Own instructions across all mapped ELF objects sum to the full raw AST profile.",
        "cells": subjects,
    }
    out = target / "codegen.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(hashlib.sha256(out.read_bytes()).hexdigest(), subjects)


if __name__ == "__main__":
    main()
