"""Install the failed release's authenticated Apple bits and reopen two original reader binaries."""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("RUNNER_TEMP", "/tmp")).resolve() / "rc22-apple-declared-smoke"
REPO = "astral-experiments/ohm"
RELEASE = "007da57ba792129adb5754546e1158e7e6d732b7"
RUST = "556a8364f1485a03be31b1a50c250d63198a943d"
READERS = {
    "packaged": "8269d772aa1ef02e5efaa331dfb40eb55d71f719",
    "fourfix": "4591cf45cc10abb19d2456c40b99606e08167f29",
    "old328": "2554a1dfaf22474b360a4298883acf41f82bd78f",
}
CODE = {
    "fourfix": "32156236e76773728b3e7655d64d32ea8c3023b165f25a2754c7e5c50669f366",
    "old328": "dd104d55d8844b9ceceb6ba0a8be3ef78ee15b890af8c6499b892fcbebba0ad6",
}
TARGET = "aarch64-apple-darwin"
NAME = "ohm-1.99.0-22"
STEM = f"{NAME}-{TARGET}"
PKG = ROOT / "toolchain"
RAW = ROOT / "inputs"
OUT = ROOT / "receipts"


def need(condition, what):
    if not condition:
        raise ValueError(str(what))


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, row):
    Path(path).write_text(json.dumps(row, sort_keys=True, indent=2) + "\n")


def api(part):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/actions/{part}"]))


def get(run, head, job, artifact, name, expected_size, checksum):
    a = api(f"artifacts/{artifact}")
    r = api(f"runs/{run}")
    j = api(f"jobs/{job}")
    save(
        OUT / f"origin-{artifact}.json",
        {
            "run": {k: r[k] for k in ("id", "head_sha", "head_branch", "run_attempt", "conclusion")},
            "job": j,
            "archive": a,
        },
    )
    need(
        r["id"] == a["workflow_run"]["id"] == j["run_id"] == run
        and r["repository"]["full_name"] == r["head_repository"]["full_name"] == REPO
        and r["head_sha"] == a["workflow_run"]["head_sha"] == j["head_sha"] == head
        and r["run_attempt"] == j["run_attempt"] == 1
        and r["path"]
        == (".github/workflows/release.yml" if head == RELEASE else ".github/workflows/ci.yml")
        and r["event"] == "workflow_dispatch"
        and r["conclusion"] == "failure"
        and j["id"] == job
        and j["conclusion"] == "success",
        "foreign or unqualified source workflow",
    )
    need(
        a["id"] == artifact
        and a["name"] == name
        and not a["expired"]
        and a["size_in_bytes"] == expected_size
        and a["digest"] == "sha256:" + checksum,
        "source media changed",
    )
    dest = RAW / f"{artifact}.zip"
    with (
        dest.open("xb") as f,
        subprocess.Popen(
            ["gh", "api", f"repos/{REPO}/actions/artifacts/{artifact}/zip"], stdout=subprocess.PIPE
        ) as proc,
    ):
        while piece := proc.stdout.read(1 << 20):
            need(f.tell() + len(piece) <= expected_size, "oversized source archive")
            f.write(piece)
        need(proc.wait(timeout=60) == 0 and f.tell() == expected_size, "short source archive")
    need(sha(dest) == checksum, "original ZIP SHA")
    return dest


def extract(zf, allowed, folder):
    with zipfile.ZipFile(zf) as z:
        need(
            set(z.namelist()) == set(allowed) and len(z.infolist()) == len(allowed),
            "unexpected source media",
        )
        for n in allowed:
            need(Path(n).name == n and z.getinfo(n).file_size < 600 << 20, "invalid source member")
            with (folder / n).open("xb") as out, z.open(n) as inp:
                shutil.copyfileobj(inp, out, 1 << 20)


def image(path):
    p = Path(path)
    s = p.stat()
    return {"path": str(p), "sha256": sha(p), "bytes": s.st_size, "dev": s.st_dev, "inode": s.st_ino}


def installed_tree(root):
    records = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in (*dirs, *files):
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                records[rel] = {"link": os.readlink(path)}
            elif path.is_file():
                records[rel] = {
                    "sha256": sha(path),
                    "size": path.stat().st_size,
                    "mode": path.stat().st_mode & 0o777,
                }
    return records


def environment():
    return {
        k: v
        for k, v in os.environ.items()
        if k
        in (
            "PATH",
            "HOME",
            "USER",
            "LOGNAME",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "CI",
            "GITHUB_ACTIONS",
            "COMMAND_MODE",
            "DEVELOPER_DIR",
            "SDKROOT",
            "MACOSX_DEPLOYMENT_TARGET",
            "SYSTEM_VERSION_COMPAT",
        )
    } | {
        "CARGO_INCREMENTAL": "1",
        "RUSTUP_HOME": str(ROOT / "rustup"),
        "CARGO_HOME": str(ROOT / "cargo-home"),
        "RUSTUP_AUTO_INSTALL": "0",
    }


def run():
    need(
        platform.system() == "Darwin"
        and platform.machine() == "arm64"
        and not ROOT.exists()
        and shutil.disk_usage(ROOT.parent).free > 12 << 30,
        "wrong host, used tree or insufficient input provision",
    )
    ROOT.mkdir(mode=0o700)
    OUT.mkdir()
    RAW.mkdir()
    (ROOT / "rustup").mkdir()
    (ROOT / "cargo-home").mkdir()
    release = RAW / "release"
    release.mkdir()
    subprocess.run(["xcodebuild", "-version"], check=True)
    cfg = json.loads((HERE / "registration.json").read_bytes())
    getargs = lambda a: [a[k] for k in ("run", "head", "job", "artifact", "name", "bytes", "sha256")]
    global_file = get(*getargs(cfg["global"]))
    distro = get(*getargs(cfg["distribution"]))
    sdk = get(*getargs(cfg["source_kit"]))
    extract(global_file, ["SHA256SUMS", NAME + ".json", "ohm-installer.sh"], release)
    extract(
        distro,
        [
            STEM + ".tar.gz",
            STEM + ".tar.gz.sha256",
            STEM + "-provenance.json",
            STEM + "-provenance.json.sha256",
        ],
        release,
    )
    sums = {
        n: h
        for h, n in [
            s.split("  ") for s in (release / "SHA256SUMS").read_text().splitlines() if s.strip()
        ]
    }
    required = [
        "ohm-installer.sh",
        NAME + ".json",
        STEM + ".tar.gz",
        STEM + ".tar.gz.sha256",
        STEM + "-provenance.json",
    ]
    need(
        all(sha(release / n) == sums[n] for n in required)
        and sums[STEM + ".tar.gz"] == "6dfc360826f23d06f8224696aa024b2b95d92e6f76cdd7fc822966136eed3a25",
        "failed release package digest",
    )
    need(
        (release / (STEM + ".tar.gz.sha256")).read_text().split()
        == [sums[STEM + ".tar.gz"], STEM + ".tar.gz"],
        "bad archive sidecar",
    )
    need(
        (release / (STEM + "-provenance.json.sha256")).read_text().split()
        == [sums[STEM + "-provenance.json"], STEM + "-provenance.json"],
        "bad provenance sidecar",
    )
    pr = json.loads((release / (STEM + "-provenance.json")).read_bytes())
    manifest = json.loads((release / (NAME + ".json")).read_bytes())
    need(
        pr["target"] == TARGET
        and pr["coordinator"]["revision"] == RELEASE
        and pr["manifest"]["sha256"] == sums[NAME + ".json"]
        and all(
            pr["sources"][k]["revision"] == manifest["sources"][k]["revision"] == v
            for k, v in [("cargo", READERS["packaged"]), ("rust", RUST)]
        ),
        "release source disagreement",
    )
    save(OUT / "release-provenance.json", pr)
    env = environment()
    subprocess.run(
        ["sh", release / "ohm-installer.sh"],
        env=env | {"OHM_DOWNLOAD_URL": release.as_uri(), "OHM_INSTALL_DIR": str(PKG)},
        cwd=ROOT,
        check=True,
        timeout=360,
    )
    originals = {}
    with tarfile.open(release / (STEM + ".tar.gz"), mode="r|gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if len(parts) < 4 or not member.isreg():
                continue
            _, component, *file = parts
            leaf = "/".join(file)
            if (
                (component, leaf) in [("cargo", "bin/cargo"), ("rustc", "bin/rustc")]
                or component == "rustc"
                and re.fullmatch(r"lib/librustc_driver[^/]*\.dylib", leaf)
                or component == "rust-std-" + TARGET
                and leaf.startswith("lib/rustlib/" + TARGET + "/lib/")
            ):
                need(leaf not in originals, "duplicate toolchain file")
                h = hashlib.file_digest(archive.extractfile(member), "sha256").hexdigest()
                need(sha(PKG / leaf) == h, ("installed SDK differs", leaf))
                originals[leaf] = h
    need(
        "bin/cargo" in originals
        and "bin/rustc" in originals
        and len([k for k in originals if "librustc_driver" in k]) == 1
        and len(originals) > 35,
        "unexpected installed SDK roster",
    )
    os.link(PKG / "bin/cargo", RAW / "cargo-packaged")
    kit = RAW / "source-kit"
    kit.mkdir()
    extract(sdk, ["kit.tar.zst", "members.json", "receipt.json"], kit)
    sref = cfg["source_kit"]
    need(
        all(
            sha(kit / f) == sref[k]
            for f, k in [
                ("kit.tar.zst", "kit"),
                ("members.json", "members"),
                ("receipt.json", "receipt"),
            ]
        ),
        "wrong SDK members",
    )
    rr = json.loads((kit / "receipt.json").read_bytes())
    members = json.loads((kit / "members.json").read_bytes())
    roles = {"roles/fourfix/cargo": "fourfix", "roles/pinned/cargo": "old328"}
    seen = set()
    with (
        subprocess.Popen(["zstd", "-dcq", kit / "kit.tar.zst"], stdout=subprocess.PIPE) as proc,
        tarfile.open(fileobj=proc.stdout, mode="r|") as archive,
    ):
        for item in archive:
            if item.name not in roles:
                continue
            key = roles[item.name]
            need(
                item.isreg()
                and key not in seen
                and item.mode == members[item.name]["mode"]
                and item.size == members[item.name]["bytes"]
                and members[item.name]["sha256"] == CODE[key]
                and rr["cargos"][item.name.split("/")[1]]["commit"] == READERS[key],
                "wrong known Cargo",
            )
            seen.add(key)
            out = RAW / ("cargo-" + key)
            with out.open("xb") as f:
                shutil.copyfileobj(archive.extractfile(item), f, 1 << 20)
            need(sha(out) == CODE[key], "wrong physical Cargo")
            out.chmod(item.mode)
        need(
            not proc.stdout.read().strip(b"\0") and proc.wait(timeout=30) == 0 and seen == set(CODE),
            "incomplete native readers",
        )
    vv = subprocess.check_output(["rustc", "+ohm", "-vV"], env=env, text=True)
    need(
        "commit-hash: " + RUST + "\n" in vv
        and "host: " + TARGET + "\n" in vv
        and Path(
            subprocess.check_output(["rustc", "+ohm", "--print", "sysroot"], env=env, text=True).strip()
        ).samefile(PKG),
        "wrong active Rust",
    )
    save(
        OUT / "installed.json",
        {
            "rustc_vV": vv,
            "distribution": sums,
            "files": originals,
            "installed_tree": installed_tree(PKG),
            "cargos": {k: image(RAW / ("cargo-" + k)) for k in READERS},
        },
    )


if __name__ == "__main__":
    run()
