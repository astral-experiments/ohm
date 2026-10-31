"""Replay both smoke definitions with the qualified Cargo and the GNU release distribution."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile


source = Path(__file__).resolve().parent
root = Path(os.environ["RUNNER_TEMP"]) / "rc22-candidate-replay"
root.mkdir()
reports = root / "reports"
reports.mkdir()
dist = root / "dist"
dist.mkdir()
repo = "repos/astral-experiments/ohm"
release = "ohm-1.99.0-22"
host = "x86_64-unknown-linux-gnu"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def store(name, value):
    (reports / name).write_text(json.dumps(value, indent=2) + "\n")


def gh(endpoint):
    return json.loads(subprocess.check_output(["gh", "api", repo + endpoint]))


def download(artifact_id, digest, run_id):
    obj = gh(f"/actions/artifacts/{artifact_id}")
    assert obj["digest"] == "sha256:" + digest and obj["workflow_run"]["id"] == run_id and not obj["expired"]
    store(f"artifact-{artifact_id}.json", obj)
    target = root / f"{artifact_id}.zip"
    with target.open("xb") as dest:
        subprocess.run(["gh", "api", repo + f"/actions/artifacts/{artifact_id}/zip"], stdout=dest, check=True)
    assert target.stat().st_size == obj["size_in_bytes"] and sha(target) == digest
    return zipfile.ZipFile(target)


inputs = json.loads((source / "release-artifacts.json").read_bytes())["artifacts"]
for key in [release + "-global", release + "-" + host]:
    item = inputs[key]
    with download(item["id"], item["digest"].removeprefix("sha256:"), 41237680370) as pkg:
        for f in pkg.namelist():
            assert Path(f).name == f
            with pkg.open(f) as inp, (dist / f).open("xb") as out:
                shutil.copyfileobj(inp, out, 2**20)
hashes = {n: h for h, n in [r.split(maxsplit=1) for r in (dist / "SHA256SUMS").read_text().splitlines()]}
for n in ["ohm-installer.sh", release + ".json", release + "-" + host + ".tar.gz"]:
    assert sha(dist / n) == hashes[n]
assert hashes[release + ".json"] == "68c7d720adfc40e7f0cb617b0b1de0621346df863328bd9b56de7c4d516a4ffd"
expected = json.loads((source / "candidate-225-sdk-gnu.json").read_bytes())
with download(expected["artifact"], expected["archive_sha256"], expected["run"]) as pkg:
    assert set(pkg.namelist()) == {"kit.tar.zst", "members.json", "receipt.json"}
    for n, key in [("kit.tar.zst","kit"),("members.json","members"),("receipt.json","receipt")]:
        with pkg.open(n) as inp, (root / n).open("xb") as out:
            shutil.copyfileobj(inp, out, 2**20)
        assert sha(root / n) == expected[key]
member = json.loads((root / "members.json").read_bytes())["roles/fourfix/cargo"]
cargo = root / "cargo-fourfix"
with subprocess.Popen(["zstd", "-dqc", root / "kit.tar.zst"], stdout=subprocess.PIPE) as proc:
    with tarfile.open(fileobj=proc.stdout, mode="r|") as kit:
        for entry in kit:
            if entry.name.removeprefix("./") == "roles/fourfix/cargo":
                assert entry.isfile()
                with kit.extractfile(entry) as inp, cargo.open("xb") as out:
                    shutil.copyfileobj(inp, out, 2**20)
    assert proc.wait() == 0
assert sha(cargo) == member["sha256"] == "33b8a25b5277671b0ce95070f8e749801b4f6e643efcbabc0ff08e6086a9c219"
cargo.chmod(0o755)
env = {k:v for k,v in os.environ.items() if not k.startswith(("CARGO_", "RUST", "OHM_", "LLVM_", "GH_TOKEN"))}
env.update(RUSTUP_HOME=str(root / "rustup"), CARGO_HOME=str(root / "cargo-home"),
           TMPDIR=str(root / "tmp"), OHM_INSTALL_DIR=str(root / "released"),
           OHM_DOWNLOAD_URL=dist.as_uri())
for name in ["rustup","cargo-home","tmp"]:
    (root / name).mkdir()
with (reports / "install.log").open("xb") as log:
    subprocess.run(["sh", dist / "ohm-installer.sh"], cwd=root, env=env, check=True,
                   stdout=log, stderr=subprocess.STDOUT)
mixed = root / "candidate"
(mixed / "bin").mkdir(parents=True)
for f in (root / "released").iterdir():
    if f.name != "bin":
        (mixed / f.name).symlink_to(f, target_is_directory=f.is_dir())
for f in (root / "released/bin").iterdir():
    (mixed / "bin" / f.name).symlink_to(cargo if f.name == "cargo" else f)
alias = "ohm-native-proof"
subprocess.run(["rustup","toolchain","link",alias,mixed], cwd=root, env=env, check=True)
tools = {n:subprocess.check_output([n, "+"+alias, "-vV"], env=env, cwd=root, text=True) for n in ("rustc","cargo")}
assert "commit-hash: 4591cf45cc10abb19d2456c40b99606e08167f29" in tools["cargo"] and host in tools["rustc"]
store("tools.json", tools)
rows = []
for name, digest in [("original","be92fafc84b4e74000f9fdc0f093debf17e591bc7e22c2fff7fc0a780bf8f38f"),
                     ("revised","9f259bbbe7949cf46079d0af4fb7a6b17ea541c8913cda99d307d977c815cc30")]:
    script = source / (name + ".sh")
    assert sha(script) == digest
    log = reports / (name + ".log")
    with log.open("xb") as dest:
        code = subprocess.run(["bash", script, alias, root / name], cwd=root, env=env, stdout=dest,
                              stderr=subprocess.STDOUT).returncode
    rows.append({"definition":name,"exit":code,"script":digest,"log":sha(log)})
    store("comparisons.json", rows)
assert rows[0]["exit"] == 1 and rows[1]["exit"] == 0, rows
assert "Expected 0 linker calls for two executables returning 17, observed 2" in " ".join((reports / "original.log").read_text().split())
subprocess.run(["python3","-IB",source / "mixed.py","225",str(root),str(root / "rustup"),
                str(root / "original/declared"),host], cwd=root, env=env, check=True)
result = root / "mixed-declared-225"
for p in result.rglob("*.log"):
    if p.name != "build.log" or p.parent.parent != result:
        continue
    shutil.copyfile(p,reports / ("mixed-" + p.parent.name + ".log"))
shutil.copyfile(result / "result.json", reports / "mixed.json")
print("Replayed both smoke definitions and preserved the mixed-input comparison.")
