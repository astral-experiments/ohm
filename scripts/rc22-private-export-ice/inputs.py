"""Reopen the held distribution and the separately built, byte-pinned four-fix native Cargo."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native import CARGO_SHA, HOST, need, save, sha


PREVIOUS_RUN = 41253059219
PREVIOUS_HEAD = "7c72fac69169e702015bd779948847d761fa30b2"
PREVIOUS_JOB = 124690404506
PREVIOUS_ARTIFACT = 13062600899
PREVIOUS_ZIP = "41b192a89d970acdc88dcc71da50a7e0e981549ccfb136215e7e5b03746771e9"
PREVIOUS_RMETA = "1f38f5367ebc64a846729456a9764280beb94182fa00b6d3fd4e48d68e21c4ae"


def previous(w, repository):
    def command(p):
        return ["gh","api",f"repos/{repository}/actions/"+p]
    def get(p):
        return json.loads(subprocess.check_output(command(p)))
    run=get(f"runs/{PREVIOUS_RUN}");job=get(f"jobs/{PREVIOUS_JOB}");a=get(f"artifacts/{PREVIOUS_ARTIFACT}")
    need(run["head_sha"]==job["head_sha"]==a["workflow_run"]["head_sha"]==PREVIOUS_HEAD
         and run["id"]==job["run_id"]==a["workflow_run"]["id"]==PREVIOUS_RUN
         and run["repository"]["full_name"]==repository and run["run_attempt"]==job["run_attempt"]==1
         and run["conclusion"]==job["conclusion"]=="failure" and job["id"]==PREVIOUS_JOB and
         run["event"]=="workflow_dispatch" and run["path"]==".github/workflows/ci.yml" and
         run["head_branch"]=="charlie/qa-rc22-private-export-ice-20261031","different prior qualification")
    names={s["name"]:s["conclusion"] for s in job["steps"]}
    need([n for n in names if names[n]=="failure"]==["Execute named new and existing rustc run-make regressions"]
         and all(names[n]=="success" for n in ("Bootstrap GNU candidate compiler, std and rustdoc",
         "Independently exercise both metadata readers and identical-stamp graph migration",
         "Retain original streams and native outputs on every outcome")),"different previous native checks")
    need(a["id"]==PREVIOUS_ARTIFACT and a["name"]=="native-private-export-qualification-gnu" and not a["expired"]
         and a["size_in_bytes"]==15075877 and a["digest"]=="sha256:"+PREVIOUS_ZIP,"different prior collection")
    z=w/"media/previous.zip"
    with z.open("xb") as dst:
        subprocess.run(command(f"artifacts/{PREVIOUS_ARTIFACT}/zip"),stdout=dst,check=True)
    need(sha(z)==PREVIOUS_ZIP and z.stat().st_size==a["size_in_bytes"],"wrong prior bytes")
    output=w/"receipts/previous";output.mkdir()
    with zipfile.ZipFile(z) as f:
        for name in ("libsubject.rmeta","headers.json"):
            path="receipts/formats/reuse-C/"+name
            need(f.namelist().count(path)==1,"wrong prior files")
            (output/name).write_bytes(f.read(path))
    header=json.loads((output/"headers.json").read_bytes())
    need(sha(output/"libsubject.rmeta")==header["actual"]==PREVIOUS_RMETA and header["generation"]==9 and
         header["version"].endswith("(Ohm metadata 2)"),"wrong prior physical rmeta")
    save(output/"origin.json",{"run":run,"job":job,"artifact":a})


def main(w):
    archived = Path(os.environ["GITHUB_WORKSPACE"]) / "native-reader"
    head = subprocess.check_output(["git", "-C", archived, "rev-parse", "HEAD"], text=True).strip()
    need(head == "69af8fd3bf8ef6ddb49aa801f25016c6af5171a9", "different official reader")
    sys.path.insert(0, str(archived / "scripts/rc22-complete-smoke"))
    import media
    import focused
    import installed
    import replay_static
    import static_cargo

    (w / "media").mkdir(parents=True)
    (w / "receipts").mkdir(exist_ok=True)
    previous(w, media.REPO)
    archives = [media.fetch(w, media.CFG["global"], "Retain global release assets"),
                media.fetch(w, media.CFG["targets"][HOST]["platform"], "Retain distribution artifacts")]
    media.release(w, HOST, *archives)
    installed.catalog(w, HOST)
    evidence = w / "receipts/original-package"
    evidence.mkdir()
    _, prefix, _ = focused.installation(w, HOST, "native-baseline", evidence)
    (w / "baseline").symlink_to(prefix, target_is_directory=True)
    jid, _, aid, size, checksum = replay_static.IDS[HOST]
    api = "repos/" + media.REPO + "/actions/"
    def command(suffix):
        return ["gh", "api", api + suffix]
    run, job, art = [json.loads(subprocess.check_output(command(suffix)))
                     for suffix in [f"runs/{replay_static.RUN}", f"jobs/{jid}", f"artifacts/{aid}"]]
    replay_static.official(run, job, art, HOST)
    native_zip = w / "media/fourfix.zip"
    with native_zip.open("xb") as out:
        subprocess.run(command(f"artifacts/{aid}/zip"), stdout=out, check=True)
    need(native_zip.stat().st_size == size and sha(native_zip) == checksum, "different native static archive")
    with zipfile.ZipFile(native_zip) as z:
        for name in ("static-product.json", "static-cargo.zst"):
            need(z.namelist().count(name) == 1, ("wrong native member", name))
            dst = w / ("receipts" if name.endswith(".json") else "media") / name
            with z.open(name) as fd, dst.open("xb") as out:
                shutil.copyfileobj(fd, out)
    origin = static_cargo.verify_product(receipt=w / "receipts/static-product.json")
    need(origin["sha256"] == CARGO_SHA, "unexpected linked Cargo")
    new = w / "fourfix"
    subprocess.run(["zstd", "-dq", w / "media/static-cargo.zst", "-o", new], check=True)
    new.chmod(0o755)
    need(sha(new) == CARGO_SHA, "wrong decoded Cargo")
    save(w / "receipts/static-origin.json", {"run": run, "job": job, "artifact": art, "cargo": sha(new)})
    binary = prefix / "bin/cargo"
    need(sha(binary) == media.CFG["targets"][HOST]["cargo_sha256"], "different original packaged Cargo")
    binary.rename(prefix / "bin/cargo.original")
    shutil.copy2(new, binary)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
