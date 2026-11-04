"""Authenticate the separately trained candidate artifact from each original release factory."""
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from records import file_hash, load

HERE = Path(__file__).resolve().parent


def enrolled(role, plan):
    pins = load(HERE / "transport" / (role + ".json"))
    source = plan["roles"][role]
    assert (pins["run"], pins["qa"]) == (source["run"], source["qa"])
    assert (pins["script"], pins["config"]) == (plan["recipe"]["script"], plan["recipe"]["config"])
    assert pins["members_sha256"] == file_hash(HERE / "transport" / (role + "-members.json"))
    return {**source, **pins}


def open_proof(z, spec, plan):
    names = z.namelist()
    assert len(names) == len(set(names)) and z.testzip() is None
    assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names)
    raw = lambda n: json.loads(z.read(n + ".json"))
    source, sdk, training = (raw(n) for n in ("source", "sdk", "training"))
    assert source["role"] == sdk["role"] == spec["factory_role"] == "candidate"
    assert (source["factory"], int(source["run"]), source["source"], source["tree"]) == (
        spec["qa"], spec["run"], spec["source"], spec["tree"]
    )
    assert source["verified_release_coordinator"] == plan["recipe"]["coordinator"]
    assert source["published_source"]["cargo"] == plan["config"]
    assert "commit-hash: " + spec["source"] in sdk["versions"]["rustc"]
    assert "commit-hash: " + plan["config"] in sdk["versions"]["cargo"]
    assert z.read("sdk-sha256").decode().strip() == spec["tar"]
    assert sdk["driver"] == spec["driver"] and sdk["release_cargo"] == plan["release_members"]["bin/cargo"]["sha256"]
    assert sdk["wild"] == plan["release_members"]["lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"]["sha256"]
    config = z.read("bootstrap.toml")
    assert b'lto = "thin"' in config and b'codegen-units = 1' in config
    assert hashlib.sha256(config).hexdigest() == training["config"] == spec["config"]
    assert training["script"] == spec["script"]
    assert set(training["profiles"]) == {"rustc", "rustdoc", "clippy", "rustfmt"}
    assert all(len(bytes.fromhex(h)) == 32 and n > 0 for h, n in training["profiles"].values())
    assert b".note.bolt_info" in z.read("driver-sections.txt")
    native = raw("native")
    assert native["baseline"] == "Row(42)" and native["rejected_twice"] == "E0308"
    assert len(bytes.fromhex(native["diagnostic"])) == 32
    array = raw("array-native/verdict")
    assert array["marked_arrays"] == 4 and array["native_old"] != array["native_repaired"] == array["native_empty"]
    assert array["invalid"]["message"] == "literal out of range for `u8`"
    assert (array["invalid"]["byte_start"], array["invalid"]["byte_end"]) == (1852, 1855)
    return sdk


def acquire(role, plan, cache, dest):
    # The offline reader can reopen the original SDK proof without the live Actions client.
    import transport

    spec = enrolled(role, plan)
    cache.mkdir(parents=True, exist_ok=True)
    dest.mkdir()
    run = transport.api("actions/runs/" + str(spec["run"]))
    job = transport.api("actions/jobs/" + str(spec["job"]))
    assert run["head_sha"] == job["head_sha"] == spec["qa"] and run["event"] == "workflow_dispatch"
    assert run["run_attempt"] == job["run_attempt"] == 1 and job["run_id"] == spec["run"]
    assert run["conclusion"] == job["conclusion"] == "success"
    for label, archive_name in (("qualification", "proof"), ("sdk", "sdk")):
        aid, trusted = spec[label]
        meta = transport.api("actions/artifacts/" + str(aid))
        assert meta["workflow_run"]["id"] == spec["run"] and meta["workflow_run"]["head_sha"] == spec["qa"]
        assert meta["name"] == f"trained-{archive_name}-candidate-{spec['run']}"
        assert not meta["expired"] and meta["digest"] == "sha256:" + trusted
        assert 0 < meta["size_in_bytes"] < (5 if label == "qualification" else 900) * 2**20
        original = (dest / "qualification.zip") if label == "qualification" else (cache / (trusted + ".zip"))
        with original.open("xb") as target:
            subprocess.run(["gh", "api", f"repos/astral-experiments/ohm/actions/artifacts/{aid}/zip"], stdout=target, check=True)
        assert original.stat().st_size == meta["size_in_bytes"] and file_hash(original) == trusted
        with zipfile.ZipFile(original) as z:
            if label == "qualification":
                proof = open_proof(z, spec, plan)
            else:
                assert z.namelist() == ["sdk.tar.zst"] and z.getinfo("sdk.tar.zst").file_size < 900 * 2**20
                tar = cache / (spec["tar"] + ".tar.zst")
                with z.open("sdk.tar.zst") as stream, tar.open("xb") as target:
                    shutil.copyfileobj(stream, target, 1024 * 1024)
                assert file_hash(tar) == spec["tar"]
    return tar, proof
