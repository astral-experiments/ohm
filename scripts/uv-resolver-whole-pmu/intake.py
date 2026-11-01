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
    with output.open("xb") as f:
        subprocess.run(["gh", "api", "--method", "GET", "-H", "Accept: application/octet-stream", endpoint],
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


if __name__ == "__main__":
    main()
