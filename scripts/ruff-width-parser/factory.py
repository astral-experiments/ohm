"""Bind each experiment arm to the candidate output of its own successful source factory."""
import hashlib
from pathlib import Path
import shutil
import subprocess as sp
import zipfile

from records import file_hash, load
import transport

def acquire(spec, plan, cache, dest):
    cache.mkdir(parents=True, exist_ok=True)
    dest.mkdir()
    run = transport.api("actions/runs/" + str(spec["run"]))
    job = transport.api("actions/jobs/" + str(spec["job"]))
    assert run["head_sha"] == spec["qa"] and run["run_attempt"] == 1 and run["status"] == "completed"
    assert job["run_id"] == spec["run"] and job["conclusion"] == "success"
    # The first factory also built another role, whose installation is excluded here.
    for label in ("qualification", "sdk"):
        aid, trusted = spec[label]
        info = transport.api("actions/artifacts/" + str(aid))
        assert info["workflow_run"]["id"] == spec["run"] and not info["expired"]
        assert info["name"] == f"array-{label}-candidate-{spec['run']}"
        assert info["digest"] == "sha256:" + trusted and 0 < info["size_in_bytes"] < 650 * 2**20
        archive = cache / (trusted + ".zip")
        with archive.open("xb") as stream:
            sp.run(["gh", "api", f"repos/astral-experiments/ohm/actions/artifacts/{aid}/zip"],
                   stdout=stream, check=True)
        assert archive.stat().st_size == info["size_in_bytes"] and file_hash(archive) == trusted
        with zipfile.ZipFile(archive) as z:
            if label == "sdk":
                assert z.namelist() == ["sdk.tar.zst"] and z.getinfo("sdk.tar.zst").file_size < 650 * 2**20
                tar = cache / (spec["tar"] + ".tar.zst")
                with z.open("sdk.tar.zst") as src, tar.open("xb") as out:
                    shutil.copyfileobj(src, out)
                assert file_hash(tar) == spec["tar"]
            else:
                names = ["bootstrap.json", "probes/verdict.json", "reported-versions.json", "sdk-sha256", "sdk.json", "source.json"]
                if "array_reader_receipt" in spec:
                    names = ["array-reader.sha256", *names]
                    assert hashlib.sha256(z.read("array-reader.sha256")).hexdigest() == spec["array_reader_receipt"]
                assert sorted(z.namelist()) == names
                for name in names:
                    assert z.getinfo(name).file_size < 1024**2
                    output = dest / name
                    output.parent.mkdir(exist_ok=True)
                    output.write_bytes(z.read(name))
                identity = load(dest / "source.json")
                assert identity == {"role":"candidate", "source":spec["source"], "tree":spec["tree"],
                                    "factory":spec["qa"], "run":str(spec["run"])}
                proof = load(dest / "sdk.json")
                versions = load(dest / "reported-versions.json")
                assert proof["role"] == "candidate" and proof["versions"] == versions
                assert "commit-hash: " + spec["source"] in versions["rustc"] and "commit-hash: " + plan["config"] in versions["cargo"]
                assert proof["driver"] == spec["driver"] and proof["release_cargo"] == plan["release_members"]["bin/cargo"]["sha256"]
                assert (dest / "sdk-sha256").read_text().strip() == spec["tar"]
                assert file_hash(dest / "bootstrap.json") == "3129eb48157c6b610c65b818ac9f86269ab1257020cf12d29701a36111460993"
                checks = load(dest / "probes/verdict.json")
                assert checks["marked_arrays"] == 4 and checks["native_repaired"] == checks["native_empty"] != checks["native_old"]
    return tar, proof
