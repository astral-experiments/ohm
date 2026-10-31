"""Confirm the published branch-cache compiler and measure the separate cost of packing."""

import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent / "branch-return-pmu"
sys.path.insert(0, str(PILOT))
import worker
from bindings import OUT, ROOT, WORK, need, save, sha
from extra_provider import exercise

b = worker.b
PLAN = "e110fd5e73b3f6a8f102a9837229d8bd2644693c39aa2b6a0c75ca7de2f778d8"
BRANCH = "charlie/qa-direct-branch-cache-confirmation-20261031"
ORDERS = {
    "01": ("Foff", "Fon", "Kon"),
    "02": ("Kon", "Fon", "Foff"),
    "03": ("Fon", "Kon", "Foff"),
    "04": ("Foff", "Kon", "Fon"),
    "05": ("Kon", "Foff", "Fon"),
    "06": ("Fon", "Foff", "Kon"),
}
PREVIOUS_BOOTS = {
    "78a866b0-afbc-4843-a44c-17a8d5bf8e1a",
    "efc22aa1-dd29-4916-985b-d7a54f481433",
    "0f45fd59-1c8c-4474-8ab8-e9886ad48fda",
    "12c3aea9-28c1-4831-a481-1b614286b3b4",
    "198293fe-416e-48d0-aef9-0611a36675a0",
    "27b66717-98d6-4021-8c18-fbf15299251f",
    "3060b886-0ac1-46a3-a1c1-a3c34b9073b6",
    "30cd5b79-aac9-4ce4-b006-c3bf6d60734c",
    "3b0e4081-536a-4f6a-a945-674825be2329",
    "6b0543d0-2fd6-4b60-9dbd-0d90c66b9973",
    "701225ea-feee-4195-82a3-9a1f70d39c46",
    "cf938e9c-a8d2-4a0d-8260-fb5f89d89d65",
    "eb13685b-610e-43dd-a65e-72a6b88482f1",
}


def eligible_screen():
    """Require the reviewed three-arm screen and both original GitHub archive digests."""
    screen = json.loads((HERE / "DIRECT-SCREEN.json").read_bytes())
    run = 41219824213
    head = "43111cc1644cc2fb89cc33eac321f3e2905edf1e"
    api = f"repos/{b.REPO}/actions/runs/{run}"
    metadata = json.loads(subprocess.check_output(["gh", "api", api]))
    need((metadata["run_attempt"], metadata["head_sha"], metadata["status"], metadata["conclusion"])
         == (1, head, "completed", "success"), "original attribution run")
    listed = json.loads(subprocess.check_output(["gh", "api", api + "/artifacts?per_page=100"]))
    media = {row["name"]: (row["id"], row["size_in_bytes"], row["digest"]) for row in listed["artifacts"]
             if not row["expired"] and row["workflow_run"]["id"] == run and row["workflow_run"]["head_sha"] == head}
    need(listed["total_count"] == len(media) == 2 and screen["run"] == run and screen["head"] == head
         and screen["branch_cache_passes_exploratory_screen"] is True, "original attribution evidence")
    for pos in ("01", "02"):
        artifact = screen["artifacts"][pos]
        need(media["branch-cache-attribution-" + pos] == (artifact["id"], artifact["size_in_bytes"],
                                                           "sha256:" + artifact["sha256"]), "original ZIP changed")
        arms = screen["hosts"][pos]["arms"]
        for phase in ("return-A", "return-B"):
            before = arms["Foff"][phase]["instructions"]
            after = arms["Fon"][phase]["instructions"]
            need(type(before) is type(after) is int and before >= 2 * after > 0, "original screen missed threshold")
    boots = {v["boot"] for v in screen["hosts"].values()}
    need(set(screen["hosts"]) == {"01", "02"} and len(boots) == 2, "original screen collection")
    return boots


def compare_clean(refs):
    for branch in ("A", "B"):
        reference = refs["Foff", branch]
        for arm in ("Fon", "Kon"):
            other = refs[arm, branch]
            need(
                reference["typed"] == other["typed"]
                and reference["graph"] == other["graph"],
                ("clean typed graph", arm, branch),
            )
            need(
                worker.same_products(reference["products"], other["products"]),
                ("clean behavior", arm, branch),
            )
            for binary in ("cli", "reader"):
                for key in ("executable", "loads"):
                    need(
                        reference["products"][binary][key]
                        == other["products"][binary][key],
                        ("clean ELF", arm, branch, binary, key),
                    )


def compare_histories(records):
    for phase, _ in worker.PHASES:
        for arm in ORDERS["01"]:
            ordinary, measured = (
                records[lane, arm][phase] for lane in ("ordinary", "measured")
            )
            need(
                {
                    k: v
                    for k, v in ordinary.items()
                    if k not in ("instructions", "allocated")
                }
                == {
                    k: v
                    for k, v in measured.items()
                    if k not in ("instructions", "allocated")
                },
                ("ordinary/metered behavior", arm, phase),
            )
            need(
                ordinary["instructions"] is None and measured["instructions"] > 0,
                ("only the calibrated command can carry counts", arm, phase),
            )
        rows = [records["ordinary", arm][phase] for arm in ORDERS["01"]]
        for key in ("source", "status", "graph", "dirty_digest"):
            need(
                all(row.get(key) == rows[0].get(key) for row in rows),
                ("matched arms", phase, key),
            )


def main(position, source, calibrator, observers, provider):
    order = ORDERS[position]
    head = os.environ["GITHUB_SHA"]
    need(
        os.environ["GITHUB_REPOSITORY"] == b.REPO
        and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and head == os.environ["REVIEWED_HEAD"] == b.git(HERE, "rev-parse", "HEAD")
        and sha(HERE / "DIRECT-CONFIRMATION.md") == PLAN,
        "six-boot direct confirmation identity",
    )
    trees = b.git(
        HERE,
        "rev-parse",
        "HEAD:scripts/branch-return-pmu",
        "HEAD:scripts/ohm-packed-ruff",
    )
    need(
        trees.splitlines()
        == [
            "8036cb549845a905ab83882f5b01766229e0e636",
            "d9fd6c8e4152d468a3a40d600ee1c6ebda13e5f2",
        ],
        "historical readers",
    )
    oracle = json.loads((PILOT / "historical-sources.json").read_bytes())
    need(
        all(
            sha(HERE.parents[1] / name) == wanted
            for name, wanted in oracle["files"].items()
        ),
        "missing historical source or reader",
    )
    need(
        ROOT.resolve() == ROOT
        and (WORK / ".owned-by-packed-study").read_text() == str(ROOT)
        and shutil.disk_usage(OUT).free >= 32 * 2**30,
        "fresh runner capacity",
    )
    for name in ("clean", "ordinary", "measured", "providers", "initial"):
        (OUT / name).mkdir()
    screen_boots = eligible_screen()
    shutil.copy2(HERE / "DIRECT-CONFIRMATION.md", OUT / "PLAN.md")
    shutil.copy2(b.RUNTIME, OUT / "source-kit.json")
    worker.link_diagnostic.acquire()
    subprocess.run(
        [sys.executable, "-IB", PILOT / "meter.py", calibrator, observers], check=True
    )
    ready = json.loads((OUT / "meter-ready.json").read_bytes())
    os.sched_setaffinity(0, ready["affinity"])
    need(
        ready["boot"] not in PREVIOUS_BOOTS | screen_boots
        and sorted(os.sched_getaffinity(0)) == ready["affinity"],
        "reused boot or wrong affinity",
    )
    save(
        OUT / "enrollment.json",
        dict(
            position=position,
            order=order,
            head=head,
            attempt=1,
            boot=ready["boot"],
            run=int(os.environ["GITHUB_RUN_ID"]),
            runner=os.environ["RUNNER_NAME"],
            source=b.spec(),
            plan=PLAN,
            attribution_screen=sha(HERE / "DIRECT-SCREEN.json"),
            command=worker.CARGO,
        ),
    )
    registry = b.acquire(source)
    env = b.activate(order[0], registry, OUT / "initial")
    b.fresh_outputs()
    b.prepare_inputs(worker.kit, env)
    worker.historical.calibration()
    refs = {}
    for arm in order:
        worker.install(arm, "clean", registry, refs, OUT / "clean" / arm)
    compare_clean(refs)
    exercise(registry, provider, order)
    records = {}
    for lane in ("ordinary", "measured"):
        for arm in order:
            records[lane, arm] = worker.install(
                arm, lane, registry, refs, OUT / lane / arm
            )
    compare_histories(records)
    archives = {
        p.name: sha(p) for p in (b.HOME / ".cargo/registry/cache").glob("*/*.crate")
    }
    need(
        len(archives) == 505
        and archives == json.loads((OUT / "ruff-inputs.json").read_bytes())["archives"],
        "changed Ruff registry",
    )
    for role, expected in registry.items():
        path = b.PARK / role
        need(
            b.inventory(path if path.exists() else b.SDK) == expected,
            ("changed SDK", role),
        )
    save(
        OUT / "sdk" / "terminal.json",
        dict(
            both_complete_byte_and_inode_inventories_unchanged=True,
            registry=worker.historical.commit(archives),
        ),
    )
    save(
        OUT / "complete.json",
        dict(
            host_complete=True,
            arms=order,
            phases=[p for p, _ in worker.PHASES],
            raw_counts_unscaled=True,
            requires_independent_cross_host_replay=True,
        ),
    )


if __name__ == "__main__":
    try:
        main(sys.argv[1], *map(Path, sys.argv[2:]))
    except BaseException:
        if OUT.exists():
            (OUT / "failure.txt").write_text(traceback.format_exc())
        raise
