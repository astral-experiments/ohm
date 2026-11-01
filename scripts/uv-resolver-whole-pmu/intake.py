"""Admit source-pinned releases and exact private build artifacts on the hosted runner."""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = json.loads((HERE / "protocol.json").read_bytes())
REPO = "astral-experiments/ohm"


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def scope():
    check(datetime.datetime.now(datetime.timezone.utc) < datetime.datetime.fromisoformat(P["dispatch_deadline_utc"]),
          "experiment registration expired")
    check(os.environ["GITHUB_REPOSITORY"] == REPO and
          os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch" and
          os.environ["GITHUB_REF"] == "refs/heads/" + P["workflow_branch"] and
          os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"] and
          os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "wrong run or reviewed head")


def hosted_roots():
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    return workspace, workspace / "trait-results", Path(os.environ["RUNNER_TEMP"]).resolve()


def gh_json(*args):
    return json.loads(subprocess.check_output(["gh", *args], timeout=120))


def gh_bytes(endpoint, output, size, digest):
    check(shutil.disk_usage(output.parent).free > size + (20 << 30), "runner disk floor")
    headers = ["-H", "Accept: application/octet-stream"] if "/releases/assets/" in endpoint else []
    with output.open("xb") as f:
        subprocess.run(["gh", "api", "--method", "GET", *headers, endpoint],
                       stdout=f, check=True, timeout=600)
    check(output.stat().st_size == size and sha(output) == digest, f"archive mismatch: {output.name}")


def sdk_input(root, result, name, protocol):
    ident = protocol["artifact_id"]
    ep = f"repos/{REPO}/actions/artifacts/{ident}"
    meta = gh_json("api", "--method", "GET", ep)
    check(meta["id"] == ident and not meta["expired"] and meta["name"] == protocol["name"] and
          meta["size_in_bytes"] == protocol["compressed_bytes"] and
          meta["digest"] == "sha256:" + protocol["outer_sha256"] and
          meta["workflow_run"]["id"] == P["build_run"] and
          meta["workflow_run"]["head_sha"] == P["build_head"], "wrong SDK Actions owner, revision or digest")
    folder = root / protocol["name"]
    folder.mkdir()
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        archive = Path(tmp) / "sdk.zip"
        gh_bytes(ep + "/zip", archive, protocol["compressed_bytes"], protocol["outer_sha256"])
        required = {"ohm.tar.gz", "SHA256SUMS", "source.json"}
        if name != "base":
            required |= {"fixture/reader.rs", "fixture/roster.rs", "fixture/rmake.rs"}
        with zipfile.ZipFile(archive) as z:
            check(set(z.namelist()) == required and len(z.infolist()) == len(required), "unexpected SDK ZIP entries")
            for item in z.infolist():
                cap = (620 << 20) if item.filename == "ohm.tar.gz" else (2 << 20)
                check(0 < item.file_size <= cap, "unexpected SDK member size")
                dst = folder / item.filename
                dst.parent.mkdir(exist_ok=True)
                with z.open(item) as src, dst.open("xb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
    check(sha(folder / "ohm.tar.gz") == protocol["inner_sha256"], "inner toolchain digest")
    save(result / ("github-artifact-" + name + ".json"), meta)


def checked_action_artifact(cfg, run, head, folder, output):
    ident = cfg["id"]
    ep = f"repos/{REPO}/actions/artifacts/{ident}"
    meta = gh_json("api", "--method", "GET", ep)
    check(meta["id"] == ident and not meta["expired"] and meta["name"] == cfg["name"] and
          meta["size_in_bytes"] == cfg["size_in_bytes"] and meta["digest"] == cfg["digest"] and
          meta["workflow_run"]["id"] == run and meta["workflow_run"]["head_sha"] == head, "wrong final Actions artifact")
    save(folder / f"github-artifact-{ident}.json", meta)
    gh_bytes(ep + "/zip", output, cfg["size_in_bytes"], cfg["digest"].removeprefix("sha256:"))


def rebased_input(root, out):
    cfg = P["final"]
    run = gh_json("api", "--method", "GET", f"repos/{REPO}/actions/runs/{cfg['run']}")
    check(run["id"] == cfg["run"] and run["head_sha"] == cfg["event"] and
          run["run_attempt"] == 1 and run["conclusion"] == "success", "wrong original release-build execution")
    job = gh_json("api", "--method", "GET", f"repos/{REPO}/actions/jobs/{cfg['job_id']}")
    check(job["run_id"] == cfg["run"] and job["conclusion"] == "success", "wrong release-build job")
    save(out / "rebased-build-run.json", run)
    save(out / "rebased-build-job.json", job)
    folder = root / "rebased"
    folder.mkdir()
    with tempfile.TemporaryDirectory(dir=root) as temp:
        zipped = Path(temp) / "release.zip"
        spec = {"id":cfg["artifact_id"], "name":cfg["name"], "size_in_bytes":cfg["compressed_bytes"],
                "digest":"sha256:" + cfg["outer_sha256"]}
        checked_action_artifact(spec, cfg["run"], cfg["event"], out, zipped)
        with zipfile.ZipFile(zipped) as z:
            check(len(z.infolist()) == len(cfg["pkg_files"]) and set(z.namelist()) == set(cfg["pkg_files"]), "release ZIP layout")
            for item in z.infolist():
                pin = cfg["pkg_files"][item.filename]
                check(not item.is_dir() and Path(item.filename).name == item.filename and item.file_size == pin["bytes"],
                      "release component size or name")
                path = folder / item.filename
                with z.open(item) as src, path.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                check(sha(path) == pin["sha256"], "authenticated release member digest")
        for src in [cfg["name"] + ".tar.gz", cfg["name"] + "-provenance.json"]:
            check((folder / (src + ".sha256")).read_text().split() == [cfg["pkg_files"][src]["sha256"], src], "release checksum sidecar")
        provenance = read(folder / (cfg["name"] + "-provenance.json"))
        check(provenance == cfg["provenance"], "source, coordinator, target or manifest mismatch")
        save(out / "rebased-provenance.json", provenance)
        qa = Path(temp) / "qa.zip"
        checked_action_artifact(cfg["qa"], cfg["run"], cfg["event"], out, qa)
        with zipfile.ZipFile(qa) as z:
            context = json.loads(z.read("context.json"))
            source = json.loads(z.read("source.json"))
            complete = json.loads(z.read("pgo/complete.json"))
            check(context == cfg["qa_context"] and source["rust_tail"]["chain"][0] ==
                  [cfg["source_commit"], "0a38b3aa6d1bbb55ec5e8c01c9e88d1cf0f9f118", cfg["source_tree"]] and
                  source["epoch"] == P["format_epochs"]["rebased"] and complete["outcome"] == "success",
                  "build QA sources, end state or epoch changed")
            members = {}
            for name, suffix in (("bin/rustc","/stage2/bin/rustc"), ("bin/cargo","/stage2-tools-bin/cargo"),
                                 ("lib/librustc_driver-b03bf00bec23bb9a.so","/stage2/lib/librustc_driver-b03bf00bec23bb9a.so")):
                found = [pair for key, pair in complete["present_after_build"].items() if key.endswith(suffix)]
                check(found == [cfg["expected_installed"][name]], "stage2 component digest")
                members[name] = found[0]
            save(out / "rebased-qa-binaries.json", members)
            save(out / "rebased-qa-context.json", context)


def released(root, result):
    cfg = P["signed"]
    tag = cfg["tag"]
    release = gh_json("api", "--method", "GET", f"repos/{REPO}/releases/tags/{tag}")
    check(release["immutable"] and not release["draft"] and not release["prerelease"] and
          release["tag_name"] == tag and release["target_commitish"] == cfg["coordinator"], "wrong signed release")
    save(result / "official-release.json", release)
    folder = root / "signed"
    folder.mkdir()
    for name, signed in cfg["assets"].items():
        matches = [row for row in release["assets"] if row["name"] == name]
        check(len(matches) == 1 and all(matches[0][key] == signed[key] for key in ("id", "digest", "size")), name)
        gh_bytes(f"repos/{REPO}/releases/assets/{signed['id']}", folder / name,
                 signed["size"], signed["digest"].removeprefix("sha256:"))
    archive, = folder.glob("*.tar.gz")
    proof = gh_json("release", "verify-asset", tag, str(archive), "--repo", REPO, "--format", "json")
    vr = proof["verificationResult"]
    statement = vr["statement"]
    check(vr["signature"]["certificate"]["subjectAlternativeName"] == "https://dotcom.releases.github.com" and
          statement["predicateType"] == "https://in-toto.io/attestation/release/v0.2" and
          statement["predicate"]["repository"] == REPO and statement["predicate"]["tag"] == tag and
          any(row.get("digest", {}).get("sha256") == sha_record(cfg, archive.name)
              for row in statement["subject"]), "release attestation does not cover this archive")
    manifest = folder / (tag + ".json")
    provenance, = folder.glob("*-provenance.json")
    pv = read(provenance)
    check(pv["target"] == P["target"] and pv["toolchain"] == tag and
          pv["coordinator"] == {"repository": REPO, "revision": cfg["coordinator"]} and
          pv["manifest"]["sha256"] == sha(manifest) and
          pv["sources"]["rust"]["revision"] == cfg["rust"] and
          pv["sources"]["cargo"]["revision"] == cfg["cargo"], "signed source provenance")
    save(result / "signed-attestation.json", proof)
    save(result / "signed-provenance.json", pv)


def sha_record(cfg, name):
    return cfg["assets"][name]["digest"].removeprefix("sha256:")


def main():
    scope()
    w, out, _ = hosted_roots()
    out.mkdir(exist_ok=True)
    media = w / "sdk-media"
    media.mkdir()
    for name, subject in P["sdk_artifacts"].items():
        sdk_input(media, out, name, subject)
    released(media, out)
    rebased_input(media, out)


if __name__ == "__main__":
    main()
