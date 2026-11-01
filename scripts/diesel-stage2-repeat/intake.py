"""Verify one previously uploaded instrumented Darwin SDK before materializing regular files."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "darwin-pgo-diesel"))
from escrow import GIB, free_guard
from identity import need, sha, write

BIND = json.loads((HERE / "enrollment.json").read_bytes())


def official(run, job, artifact):
    b = BIND
    need(
        (
            run["id"],
            run["head_sha"],
            run["head_branch"],
            run["run_attempt"],
            run["event"],
            run["path"],
            run["status"],
            run["conclusion"],
        )
        == (
            b["run"],
            b["head"],
            b["branch"],
            b["attempt"],
            "workflow_dispatch",
            ".github/workflows/ci.yml",
            "completed",
            "success",
        ),
        "wrong source action",
    )
    need(
        run["repository"]["full_name"] == run["head_repository"]["full_name"] == b["repository"],
        "wrong source repository",
    )
    need(
        (job["id"], job["run_id"], job["run_attempt"], job["head_sha"], job["name"], job["conclusion"])
        == (b["job"], b["run"], 1, b["head"], b["job_name"], "success"),
        "wrong source job",
    )
    required = {
        "Run the original optimized release command through all rustc PGO benchmarks",
        "Authenticate and escrow the instrumented native compiler and exact Cargo",
        "Save native instrumented runtime",
        "Run pinned original collector with only the real Diesel Opt benchmark",
    }
    need(required <= {s["name"] for s in job["steps"] if s["conclusion"] == "success"}, "source gates missing")
    need(
        all(artifact[k] == v for k, v in b["official"].items())
        and not artifact["expired"]
        and (artifact["workflow_run"]["id"], artifact["workflow_run"]["head_sha"]) == (b["run"], b["head"]),
        "wrong source ZIP",
    )


def copy_stream(src, dst=None):
    h = hashlib.sha256()
    while block := src.read(1 << 20):
        h.update(block)
        if dst is not None:
            dst.write(block)
    return h.hexdigest()


def members(stream, expected, dest=None):
    """This captured SDK has no symlinks or repeated file inodes."""
    rows = expected["entries"]
    seen = set()
    identities = set()
    total = 0
    with tarfile.open(fileobj=stream, mode="r|gz") as tar:
        for m in tar:
            name = PurePosixPath(m.name)
            need(
                m.name in rows
                and m.name not in seen
                and name.parts
                and str(name) == m.name
                and not name.is_absolute()
                and ".." not in name.parts
                and "\\" not in m.name,
                "invalid tar member",
            )
            need(
                len(name.parts) == 1 or str(name.parent) in seen and rows[str(name.parent)]["type"] == "dir",
                "missing parent",
            )
            seen.add(m.name)
            rec = rows[m.name]
            need(m.mode == rec["mode"] and 0 <= m.mode <= 0o777, "wrong member mode")
            out = dest / m.name if dest else None
            if rec["type"] == "dir" and m.isdir():
                if out:
                    out.mkdir()
                    out.chmod(m.mode)
                continue
            need(
                rec["type"] == "file"
                and m.isreg()
                and m.size == rec["size"]
                and total + m.size <= expected["unique_bytes"],
                "wrong member type/size",
            )
            ident = (rec["dev"], rec["ino"])
            need(ident not in identities, "unexpected SDK file alias")
            identities.add(ident)
            total += m.size
            with tar.extractfile(m) as src:
                if out:
                    with out.open("xb") as dst:
                        digest = copy_stream(src, dst)
                    out.chmod(m.mode)
                else:
                    digest = copy_stream(src)
            need(digest == rec["sha256"], "different SDK payload " + m.name)
    need(seen == set(rows) and total == expected["unique_bytes"], "partial SDK")
    return {"members": len(seen), "distinct_regular_inodes": len(identities), "unique_bytes": total}


def reopen(path, dest=None):
    want = BIND["official"]
    need(
        path.stat().st_size == want["size_in_bytes"] and "sha256:" + sha(path) == want["digest"],
        "bad original ZIP",
    )
    if dest:
        need(not dest.exists(), "SDK destination already exists")
        free_guard(dest.parent, GIB)
        dest.mkdir()
    with zipfile.ZipFile(path) as z:
        names = BIND["zip_members"]
        need(sorted(z.namelist()) == sorted(names), "extra/duplicate/missing ZIP member")
        for name, (size, digest) in names.items():
            with z.open(name) as f:
                need(z.getinfo(name).file_size == size and copy_stream(f) == digest, "bad ZIP member " + name)
        inv = json.loads(z.read("instrumented-sdk.tar.inventory.json"))
        with z.open("instrumented-sdk.tar.gz") as src:
            result = members(src, inv, dest)
        need(BIND["inventory"] == result, "incomplete SDK")
    return result


def restore(root, dest, report):
    root.mkdir()
    report.mkdir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    b = BIND
    api = ["gh", "api", "repos/" + b["repository"] + "/actions/"]

    def command(suffix):
        return api[:2] + [api[2] + suffix]

    def get(suffix):
        return json.loads(subprocess.check_output(command(suffix)))

    run, job, artifact = (
        get(s) for s in (f"runs/{b['run']}", f"jobs/{b['job']}", f"artifacts/{b['official']['id']}")
    )
    official(run, job, artifact)
    write(report / "intake.json", {"run": run, "job": job, "artifact": artifact})
    media = root / "original-sdk.zip"
    free_guard(root, GIB)
    with media.open("xb") as f:
        subprocess.run(command(f"artifacts/{artifact['id']}/zip"), stdout=f, check=True)
    write(report / "sdk.json", reopen(media, dest))


if __name__ == "__main__":
    if sys.argv[1] == "verify" and len(sys.argv) == 3:
        print(json.dumps(reopen(Path(sys.argv[2])), sort_keys=True))
    elif sys.argv[1] == "restore" and len(sys.argv) == 5:
        restore(*(Path(k) for k in sys.argv[2:]))
    else:
        raise SystemExit("intake.py verify ORIGINAL_ZIP | restore NEW_WORK NEW_SDK NEW_REPORT")
