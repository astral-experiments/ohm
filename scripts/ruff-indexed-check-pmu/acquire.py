"""Reopen only the reviewed nonrelease factory archive and its independent receipts."""

import json, os, re, shutil, subprocess, sys, tarfile, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ruff-matched-stage"))
from capsule import need, reopen, sha

ROOT = Path(os.environ["RUNNER_TEMP"]) / "indexed-check-study"
LOG = ROOT / "logs"
REG = json.loads((HERE / "registration.json").read_bytes())


def json_save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def api(tail):
    return json.loads(
        subprocess.check_output(["gh", "api", "repos/astral-experiments/ohm/" + tail])
    )


def main():
    ROOT.mkdir()
    LOG.mkdir()
    key = REG["factory_run"]
    repo = "astral-experiments/ohm"
    r = api("actions/runs/" + str(key))
    need(
        (
            r["head_sha"],
            r["head_branch"],
            r["status"],
            r["conclusion"],
            r["event"],
            r["run_attempt"],
            r["head_repository"]["full_name"],
        )
        == (
            REG["factory_head"],
            REG["factory_branch"],
            "completed",
            "success",
            "workflow_dispatch",
            1,
            repo,
        ),
        "wrong factory run",
    )
    artifacts = {
        a["name"]: a
        for a in api("actions/runs/" + str(key) + "/artifacts")["artifacts"]
    }
    base = "ohm-indexed-check-matched-stage1"
    selected = {}
    for name in (base + "-receipts", base):
        a = artifacts[name]
        need(
            not a["expired"]
            and a["workflow_run"]["id"] == key
            and 0 < a["size_in_bytes"] < 1600 * 2**20,
            "wrong artifact",
        )
        zip_path = ROOT / (name + ".zip")
        with zip_path.open("xb") as output:
            subprocess.run(
                [
                    "gh",
                    "api",
                    "repos/" + repo + "/actions/artifacts/" + str(a["id"]) + "/zip",
                ],
                stdout=output,
                check=True,
            )
        need(
            a["digest"] == "sha256:" + sha(zip_path),
            "different uploaded artifact bytes",
        )
        selected[name] = {
            "id": a["id"],
            "digest": a["digest"],
            "bytes": zip_path.stat().st_size,
        }
        with zipfile.ZipFile(zip_path) as archive:
            if name.endswith("-receipts"):
                names = archive.namelist()
                expected = archive.read("archive.sha256").decode()
                fmt = {
                    role: json.loads(archive.read("check-format-" + role + ".json"))
                    for role in ("normal", "defer")
                }
                json_save(LOG / "physical-formats.json", fmt)
                need(
                    all(
                        set(v["version"] for v in fmt[k].values()) == {version}
                        for k, version in [("normal", 10), ("defer", 11)]
                    ),
                    "factory missed graph versions",
                )
                need(
                    re.fullmatch(r"[0-9a-f]{64}  matched-stage.tar.zst\s*", expected)
                    is not None,
                    "bad archive checksum",
                )
            else:
                need(
                    archive.namelist() == ["matched-stage.tar.zst"],
                    "extra transport member",
                )
                compressed = ROOT / "matched-stage.tar.zst"
                with (
                    archive.open("matched-stage.tar.zst") as inp,
                    compressed.open("xb") as output,
                ):
                    shutil.copyfileobj(inp, output, 2**20)
                need(sha(compressed) == expected.split()[0], "changed capsule archive")
        zip_path.unlink()
    cap = ROOT / "capsule"
    (cap / "objects").mkdir(parents=True)
    seen = set()
    total = 0
    with subprocess.Popen(
        ["zstd", "-q", "-dc", compressed], stdout=subprocess.PIPE
    ) as dec:
        with tarfile.open(fileobj=dec.stdout, mode="r|") as archive:
            for item in archive:
                name = item.name.rstrip("/")
                if name in ("capsule", "capsule/objects"):
                    need(item.isdir(), "unexpected directory")
                    continue
                need(
                    item.isfile()
                    and name not in seen
                    and (
                        re.fullmatch(r"capsule/objects/[0-9a-f]{64}", name)
                        or name
                        in (
                            "capsule/P.json",
                            "capsule/C.json",
                            "capsule/qualified.json",
                        )
                    ),
                    "unsafe capsule member",
                )
                total += item.size
                need(
                    0 < item.size <= 700 * 2**20 and total < 5200 * 2**20,
                    "oversize capsule",
                )
                with (
                    archive.extractfile(item) as inp,
                    (ROOT / name).open("xb") as output,
                ):
                    shutil.copyfileobj(inp, output, 2**20)
                need(0 < item.mode <= 0o777, "invalid mode in frozen capsule")
                os.chmod(ROOT / name, item.mode)
                seen.add(name)
        need(dec.wait() == 0, "truncated zstd stream")
    compressed.unlink()
    manifest = reopen(cap, ROOT / "reopened")
    json_save(LOG / "compiler-installations.json", manifest)
    json_save(
        LOG / "factory.json",
        dict(
            run=key,
            head=r["head_sha"],
            artifacts=selected,
            archive_sha256=expected.split()[0],
        ),
    )


if __name__ == "__main__":
    main()
