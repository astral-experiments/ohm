"""Authenticate original release media and, separately, the source-built Cargo."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "registration.json").read_bytes())
REPO = "astral-experiments/ohm"
BRANCH = "charlie/qa-rc22-complete-input-smoke-20261031"


def need(condition, detail):
    if not condition:
        raise ValueError(detail)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def locations():
    temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    if role := os.environ.get("OHM_QA_ROLE"):
        root = temp.parent.parent
        need(
            role in ("packaged", "fourfix")
            and temp == root / "sessions" / role
            and root.name == "rc22-complete-smoke",
            "wrong child installation scope",
        )
    else:
        root = temp / "rc22-complete-smoke"
    target = os.environ["OHM_QA_TARGET"]
    need(
        (platform.system(), platform.machine())
        == {"x86_64-unknown-linux-gnu": ("Linux", "x86_64"), "aarch64-apple-darwin": ("Darwin", "arm64")}[
            target
        ],
        "wrong native platform",
    )
    return root, target


def archive_origin(spec, run, job, artifact, step):
    release = spec["run"] == 41237680370
    need(
        run["id"] == job["run_id"] == artifact["workflow_run"]["id"] == spec["run"]
        and run["head_sha"] == job["head_sha"] == artifact["workflow_run"]["head_sha"] == spec["head"]
        and run["repository"]["full_name"] == run["head_repository"]["full_name"] == REPO
        and run["path"] == (".github/workflows/release.yml" if release else ".github/workflows/ci.yml")
        and run["event"] == "workflow_dispatch"
        and run["run_attempt"] == job["run_attempt"] == 1
        and run["conclusion"] == "failure"
        and (not release or run["head_branch"] == "main")
        and job["id"] == spec["job"]
        and job["conclusion"] == "success"
        and sum(s["name"] == step and s["conclusion"] == "success" for s in job["steps"]) == 1,
        "unexpected source run, producing job or completed step",
    )
    need(
        artifact["id"] == spec["artifact"]
        and artifact["name"] == spec["name"]
        and artifact["size_in_bytes"] == spec["bytes"]
        and not artifact["expired"]
        and artifact["digest"] == "sha256:" + spec["sha256"],
        "unexpected artifact",
    )


def fetch(root, spec, step):
    prefix = ["gh", "api", f"repos/{REPO}/actions/"]

    def cmd(path):
        return prefix[:2] + [prefix[2] + path]

    run, job, artifact = [
        json.loads(subprocess.check_output(cmd(s)))
        for s in (f"runs/{spec['run']}", f"jobs/{spec['job']}", f"artifacts/{spec['artifact']}")
    ]
    archive_origin(spec, run, job, artifact, step)
    save(
        root / "receipts" / f"official-{artifact['id']}.json", {"run": run, "job": job, "artifact": artifact}
    )
    path = root / "media" / f"{artifact['id']}.zip"
    with (
        path.open("xb") as out,
        subprocess.Popen(cmd(f"artifacts/{artifact['id']}/zip"), stdout=subprocess.PIPE) as process,
    ):
        while chunk := process.stdout.read(1 << 20):
            need(out.tell() + len(chunk) <= spec["bytes"], "oversized artifact")
            out.write(chunk)
        need(process.wait(timeout=30) == 0 and out.tell() == spec["bytes"], "incomplete original ZIP")
    need(sha(path) == spec["sha256"], "different original ZIP")
    return path


def unpack(path, folder, leaves):
    with zipfile.ZipFile(path) as src:
        need(sorted(src.namelist()) == sorted(leaves), "unexpected or duplicate ZIP members")
        for name in leaves:
            info = src.getinfo(name)
            need(
                name == Path(name).name and 0 < info.file_size < 600 << 20 and not info.flag_bits & 1,
                "unsafe ZIP member",
            )
            with src.open(name) as inp, (folder / name).open("xb") as out:
                shutil.copyfileobj(inp, out, 1 << 20)


def release(root, target, global_zip, native_zip):
    spec = CFG["targets"][target]["platform"]
    need(
        sha(global_zip) == CFG["global"]["sha256"] and sha(native_zip) == spec["sha256"],
        "release media bytes",
    )
    folder = root / "release"
    folder.mkdir(mode=0o700)
    unpack(global_zip, folder, CFG["global_files"])
    stem = spec["name"]
    tar, doc = stem + ".tar.gz", stem + "-provenance.json"
    unpack(native_zip, folder, [tar, doc, tar + ".sha256", doc + ".sha256"])
    need(all(sha(folder / n) == d for n, d in CFG["global_files"].items()), "global inner commitments")
    sums = dict(
        (n, h) for h, n in (line.split("  ") for line in (folder / "SHA256SUMS").read_text().splitlines())
    )
    need(
        sums == CFG["checksums"]
        and all(sha(folder / n) == v for n, v in sums.items() if (folder / n).exists()),
        "release sums",
    )
    for n in [tar, doc]:
        need((folder / (n + ".sha256")).read_text().split() == [sha(folder / n), n], "detached release sum")
    manifest = json.loads((folder / (CFG["release"] + ".json")).read_bytes())
    stamped = json.loads((folder / doc).read_bytes())
    revisions = {k: v["revision"] for k, v in manifest["sources"].items()}
    need(
        stamped["target"] == target
        and stamped["toolchain"] == CFG["release"]
        and stamped["coordinator"]["revision"] == CFG["source"]
        and stamped["manifest"]["sha256"] == sums[CFG["release"] + ".json"]
        and {k: v["revision"] for k, v in stamped["sources"].items()} == revisions
        and all(revisions[k] == CFG[k] for k in ("rust", "cargo", "clippy")),
        "original platform source provenance",
    )
    save(
        root / "receipts/release.json",
        {
            "sources": revisions,
            "global": CFG["global"],
            "platform": spec,
            "verified_leaves": {p.name: sha(p) for p in folder.iterdir()},
            "provenance": stamped,
        },
    )


def fixed(root, target, path):
    spec = CFG["targets"][target]["native"]
    need(sha(path) == spec["sha256"], "wrong QA kit ZIP")
    kit = root / "native-source"
    kit.mkdir(mode=0o700)
    unpack(path, kit, ["kit.tar.zst", "receipt.json", "members.json"])
    need(
        all(
            sha(kit / n) == spec[k]
            for n, k in [("kit.tar.zst", "kit"), ("receipt.json", "receipt"), ("members.json", "members")]
        ),
        "changed kit members",
    )
    receipt = json.loads((kit / "receipt.json").read_bytes())
    member = json.loads((kit / "members.json").read_bytes())["roles/fourfix/cargo"]
    need(
        receipt["cargos"]["fourfix"]["commit"] == CFG["fourfix"]
        and receipt["cargos"]["fourfix"]["tree"] == CFG["fourfix_tree"]
        and member["sha256"] == CFG["targets"][target]["fourfix_sha256"],
        "wrong Cargo product",
    )
    out = root / "fourfix-cargo"
    with subprocess.Popen(["zstd", "-dcq", kit / "kit.tar.zst"], stdout=subprocess.PIPE) as process:
        with tarfile.open(fileobj=process.stdout, mode="r|", bufsize=1 << 20) as archive:
            for m in archive:
                if m.name != "roles/fourfix/cargo":
                    continue
                need(m.isreg() and m.size == member["bytes"] and m.mode == member["mode"], "wrong Cargo file")
                with out.open("xb") as dst, archive.extractfile(m) as inp:
                    shutil.copyfileobj(inp, dst, 1 << 20)
        while piece := process.stdout.read(1 << 20):
            need(not piece.strip(b"\0"), "trailing kit data")
        need(process.wait(timeout=30) == 0 and sha(out) == member["sha256"], "Cargo ELF digest mismatch")
    out.chmod(0o555)
    save(
        root / "receipts/fourfix.json",
        {"original": spec, "cargo": receipt["cargos"]["fourfix"], "member": member},
    )


def main():
    root, target = locations()
    need(
        os.environ["GITHUB_REPOSITORY"] == REPO
        and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
        and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1",
        "private branch manual first attempt required",
    )
    if sys.argv[1] == "original":
        need(
            not root.exists() and shutil.disk_usage(root.parent).free >= 10 << 30,
            "fresh runner and 10 GiB required",
        )
        root.mkdir(mode=0o700)
        (root / "media").mkdir()
        (root / "receipts").mkdir()
        save(
            root / "receipts/enrollment.json",
            {
                k: os.environ[k]
                for k in [
                    "GITHUB_SHA",
                    "GITHUB_REF",
                    "GITHUB_RUN_ID",
                    "GITHUB_RUN_ATTEMPT",
                    "RUNNER_NAME",
                    "OHM_QA_TARGET",
                ]
            },
        )
        g = fetch(root, CFG["global"], "Retain global release assets")
        p = fetch(root, CFG["targets"][target]["platform"], "Retain distribution artifacts")
        release(root, target, g, p)
    elif sys.argv[1] == "fixed":
        spec = CFG["targets"][target]["native"]
        fixed(root, target, fetch(root, spec, "Publish reusable native SDK"))
    else:
        raise SystemExit("choose original or fixed")


if __name__ == "__main__":
    main()
