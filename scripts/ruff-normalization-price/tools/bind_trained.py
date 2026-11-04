"""Verify an already collected factory against GitHub, its tar and the extracted executable kit."""
import argparse
import hashlib
import json
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE))
from factory import open_proof
from records import file_hash, load


def authorities(spec, gh):
    def api(endpoint):
        return json.loads(subprocess.check_output([gh, "api", "repos/astral-experiments/ohm/actions/" + endpoint], cwd=SUITE))
    run = api("runs/" + str(spec["run"]))
    job = api("jobs/" + str(spec["job"]))
    assert run["run_attempt"] == job["run_attempt"] == 1 and job["run_id"] == run["id"] == spec["run"]
    assert run["head_sha"] == job["head_sha"] == spec["qa"] and run["event"] == "workflow_dispatch"
    assert run["status"] == job["status"] == "completed" and run["conclusion"] == job["conclusion"] == "success"
    sizes = {}
    for kind, label in (("sdk", "sdk"), ("qualification", "proof")):
        aid, sha = spec[kind]
        meta = api("artifacts/" + str(aid))
        assert meta["name"] == f"trained-{label}-candidate-{spec['run']}" and meta["digest"] == "sha256:" + sha
        assert meta["workflow_run"]["id"] == spec["run"] and meta["workflow_run"]["head_sha"] == spec["qa"]
        assert not meta["expired"]
        sizes[kind] = meta["size_in_bytes"]
    return sizes


def actual_members(root):
    original = root / "sdk.tar.zst"
    installed = root / "sdk"
    process = subprocess.Popen(["zstd", "-qdc", original], stdout=subprocess.PIPE)
    members = {}
    total = 0
    with process.stdout, tarfile.open(fileobj=process.stdout, mode="r|") as tar:
        for entry in tar:
            name = Path(entry.name)
            assert name.parts[0] in {"lib", "bin"} and not name.is_absolute() and ".." not in name.parts
            if entry.isdir():
                continue
            assert entry.isfile() and 0 < entry.size < 650 * 2**20 and entry.name not in members
            total += entry.size
            assert total < 3 * 2**30
            file = installed / name
            attributes = file.lstat()
            assert stat.S_ISREG(attributes.st_mode) and attributes.st_size == entry.size
            assert attributes.st_mode & 0o777 == entry.mode & 0o777
            with tar.extractfile(entry) as stream:
                content_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            assert file_hash(file) == content_hash
            members[entry.name] = [content_hash, entry.size]
    assert process.wait() == 0 and set(members) == {str(f.relative_to(installed)) for f in installed.rglob("*") if f.is_file()}
    return members


def write_once(path, body):
    if path.exists():
        assert path.read_bytes() == body, path
    else:
        path.write_bytes(body)


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("role", choices=("C5", "C7"))
    cli.add_argument("root", type=Path)
    cli.add_argument("--gh-auto", default="/home/dev-user/.local/bin/gh-auto")
    args = cli.parse_args()
    plan = load(SUITE / "registration.json")
    spec = load(args.root / "consumer-bound.json")
    source = plan["roles"][args.role]
    assert (spec["run"], spec["qa"]) == (source["run"], source["qa"])
    assert (spec["script"], spec["config"]) == (plan["recipe"]["script"], plan["recipe"]["config"])
    sizes = authorities(spec, args.gh_auto)
    for kind, name in (("qualification", "proof.zip"), ("sdk", "original-sdk.zip")):
        path = args.root / name
        assert file_hash(path) == spec[kind][1] and path.stat().st_size == sizes[kind]
    with zipfile.ZipFile(args.root / "proof.zip") as z:
        sdk = open_proof(z, {**source, **spec}, plan)
    with zipfile.ZipFile(args.root / "original-sdk.zip") as z:
        assert z.namelist() == ["sdk.tar.zst"]
        with z.open("sdk.tar.zst") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == spec["tar"]
    assert file_hash(args.root / "sdk.tar.zst") == spec["tar"]
    files = actual_members(args.root)
    assert files["bin/rustc"][0] == sdk["rustc"] and files["bin/cargo"][0] == sdk["release_cargo"]
    drivers = [v[0] for name, v in files.items() if name.startswith("lib/librustc_driver-") and name.endswith(".so")]
    assert drivers == [sdk["driver"]]
    factory_members = args.root / "all-file-sha256.json"
    assert load(factory_members) == files
    # Keep the complete original file inventory, including its original JSON encoding.
    destination = SUITE / "transport"
    write_once(destination / (args.role + "-members.json"), factory_members.read_bytes())
    pins = dict(spec, members_sha256=file_hash(factory_members))
    write_once(destination / (args.role + ".json"), (json.dumps(pins, indent=2, sort_keys=True) + "\n").encode())
    print(args.role, spec["source"] if "source" in spec else source["source"], sdk["driver"], len(files), sum(f[1] for f in files.values()))


if __name__ == "__main__":
    main()
