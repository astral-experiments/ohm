"""Authenticate each original. Open and independently execute the genuine native programs on one boot at a time."""

import argparse, hashlib, json, os, shutil, statistics, subprocess as sp, sys
from pathlib import Path

REPO = "repos/astral-experiments/ohm"
GH = "/home/dev-user/.local/bin/gh-auto"


def check(ok, why):
    if not ok:
        raise ValueError(why)


def api(url):
    return json.loads(sp.check_output([GH, "api", REPO + "/" + url], timeout=90))


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def hf(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def summarize(rows):
    out = {"pairs": [], "statistics": {}, "median_secondary": {}}
    reductions = []
    for slot, z in enumerate(rows):
        roles = z["roles"]
        p, c = roles["P"], roles["C"]
        whole = lambda r, s: r["whole_user_instructions"][s]
        obs = {}
        for phase in (
            "edit",
            "observed-edit",
            "cold-old",
            "empty-new",
            "old-unchanged",
            "new-unchanged",
        ):
            a, b = whole(p, phase), whole(c, phase)
            obs[phase] = [a, b, 100 * (1 - b / a)]
        for r in (p, c):
            task = r["real_tasks"]["observed-edit"]
            check(
                "lib:src/lib.rs" in task and "test-harness:src/lib.rs" in task,
                "missing two different src/lib.rs compiler actions",
            )
            check(
                len([k for k in task if k.startswith("test-harness:")]) == 8
                and "bin:src/main.rs" in task,
                "wrong full compiler roster",
            )
            detail = r["separate_all_task_breakdown"].get("observed-edit")
            if detail is None:
                check(
                    "observed-edit" in r["refused_all_task_breakdown"],
                    "missing task attribution verdict",
                )
                continue
            check(
                len(detail["link_outputs"]) == 9
                and detail["all_tasks"]["ld.bfd"]
                == sum(detail["link_outputs"].values()),
                "unaccounted linker children",
            )
        check(
            obs["edit"][2] > 0
            and all(
                obs[p][2] >= -2
                for p in ("cold-old", "empty-new", "old-unchanged", "new-unchanged")
            ),
            "frozen primary or cold/unchanged veto",
        )
        reductions.append(obs["edit"][2])
        out["pairs"].append(
            {
                "slot": slot,
                "order": z["confirmation"]["order"],
                "boot": z["run_input"]["boot"],
                "source": z["original"],
                "whole": obs,
                "normal_library": [
                    r["real_tasks"]["observed-edit"]["lib:src/lib.rs"] for r in (p, c)
                ],
                "library_test_harness": [
                    r["real_tasks"]["observed-edit"]["test-harness:src/lib.rs"]
                    for r in (p, c)
                ],
                "all_linker_tasks": [
                    r["separate_all_task_breakdown"].get("observed-edit", {}).get("all_tasks", {}).get("ld.bfd")
                    for r in (p, c)
                ],
                "edited_storage_bytes": [
                    r["allocations"]["edit"]["allocated_unique"] for r in (p, c)
                ],
                "native_bodies": z["physical_native_bodies"],
            }
        )
    check(
        len(rows) == 6
        and len({r["boot"] for r in out["pairs"]}) == 6
        and [r["order"] for r in out["pairs"]] == ["PC", "CP", "CP", "PC", "PC", "CP"]
        and statistics.median(reductions) >= 20,
        "frozen independent boot, order or effect gate",
    )
    out["statistics"] = {
        "median_reduction_percent": statistics.median(reductions),
        "exact_untrimmed_median_interval_percent": [min(reductions), max(reductions)],
        "sign_interval_coverage_percent": 96.875,
        "two_sided_exact_sign_p": 2 / 2**6,
    }
    for k in out["pairs"][0]["whole"]:
        out["median_secondary"][k] = statistics.median(
            v["whole"][k][2] for v in out["pairs"]
        )
    for k in ("normal_library", "library_test_harness", "all_linker_tasks"):
        out["median_secondary"][k] = (
            statistics.median(100 * (1 - v[k][1] / v[k][0]) for v in out["pairs"])
            if all(None not in v[k] for v in out["pairs"])
            else None
        )
    return out


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--root", type=Path, required=True)
    cli.add_argument("--reader", type=Path, required=True)
    cli.add_argument("--ruff", type=Path, required=True)
    cli.add_argument("--run", type=int, default=41758087313)
    cli.add_argument("--head", required=True)
    a = cli.parse_args()
    a.root.mkdir(exist_ok=True, parents=True)
    rid = a.run
    meta = api("actions/runs/" + str(rid))
    jobs = api(f"actions/runs/{rid}/jobs?per_page=100")
    assets = api(f"actions/runs/{rid}/artifacts?per_page=100")
    save(a.root / "run.json", meta)
    save(a.root / "jobs.json", jobs)
    save(a.root / "assets.json", assets)
    check(
        meta["id"] == rid
        and meta["run_attempt"] == 1
        and meta["head_sha"] == a.head
        and meta["head_branch"] == "charlie/qa-ruff-cli-help-norun-six-stage2-20261104",
        "unknown exact receiver",
    )
    job_by_slot = {int(job["name"].split()[-1]): job for job in jobs["jobs"]}
    check(len(job_by_slot) == 6, "different number of workers")
    by_name = {v["name"]: v for v in assets["artifacts"]}
    rows = []
    boot = set()
    for i in range(6):
        item = by_name.get(f"ruff-28392-six-norun-{i}-{rid}")
        job = job_by_slot[i]
        if job["status"] != "completed" or item is None:
            continue
        check(
            not item["expired"]
            and item["workflow_run"]["id"] == rid
            and item["digest"].startswith("sha256:")
            and 0 < item["size_in_bytes"] < 950 << 20,
            "wrong physical archive",
        )
        root = a.root / str(i)
        root.mkdir(exist_ok=True)
        archive = root / "original.zip"
        digest = item["digest"][7:]
        save(root / "asset.json", item)
        if not archive.exists():
            check(
                shutil.disk_usage(root).free > 15 * 2**30 + 4 * item["size_in_bytes"],
                "native reader disk reserve",
            )
            tmp = root / "capture.part"
            with tmp.open("wb") as file:
                sp.run(
                    [GH, "api", f"{REPO}/actions/artifacts/{item['id']}/zip"],
                    stdout=file,
                    check=True,
                    timeout=240,
                )
            check(
                tmp.stat().st_size == item["size_in_bytes"] and hf(tmp) == digest,
                "original transport SHA",
            )
            tmp.rename(archive)
        check(
            archive.stat().st_size == item["size_in_bytes"] and hf(archive) == digest,
            "cached original changed",
        )
        result = root / "reopened.json"
        previous = root / "reader.sha256"
        reader_digest = hf(a.reader)
        if (
            not result.exists()
            or not previous.exists()
            or previous.read_text().strip() != reader_digest
        ):
            env = os.environ | {
                "CARGO_TARGET_DIR": str(root / "local-assay-target"),
                "CARGO_BUILD_BUILD_DIR": str(root / "local-assay-build"),
            }
            cmd = [
                sys.executable,
                "-IB",
                a.reader,
                "--zip",
                archive,
                "--sha256",
                digest,
                "--work",
                root,
                "--ruff",
                a.ruff,
                "--out",
                result,
            ]
            if job["conclusion"] != "success":
                cmd.append("--partial")
            sp.run(cmd, env=env, check=True)
            previous.write_text(reader_digest + "\n")
        row = json.loads(result.read_bytes())
        check(
            row["run_input"]["receiver"] == a.head
            and row["confirmation"]["slot"] == i
            and row["original"]["sha256"] == digest,
            "unbound physical admission",
        )
        check(
            job["conclusion"] == "success" and row["run_input"]["boot"] not in boot,
            "failed/substituted worker",
        )
        boot.add(row["run_input"]["boot"])
        rows.append(row)
        print("reopened slot", i, "job", job["id"], "artifact", item["id"], flush=True)
    if len(rows) == 6:
        check(meta["conclusion"] == "success", "receipt predated terminal workflow")
        result = summarize(rows)
        result["run"] = rid
        result["head"] = a.head
        save(a.root / "combined.json", result)
        print(result["statistics"], flush=True)
    else:
        print("complete authenticated workers", len(rows), "/6", flush=True)


if __name__ == "__main__":
    main()
