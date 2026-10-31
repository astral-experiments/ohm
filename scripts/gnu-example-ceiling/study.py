"""Two-host diagnostic. Publish qualified bounds only from the enrolled actual whole-command records."""

import argparse, datetime, json, os, platform, shutil, subprocess, sys, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit, pmu, workload as w, topology, ceiling
from kit import H, sha, save, ROLES


def host():
    paths = [
        "/sys/devices/cpu/caps/pmu_name",
        "/sys/devices/cpu/type",
        "/sys/devices/cpu/rdpmc",
        "/sys/devices/cpu/caps/num_counters",
        "/proc/sys/kernel/perf_event_paranoid",
        "/proc/sys/kernel/random/boot_id",
        "/sys/devices/system/cpu/online",
        "/sys/class/dmi/id/product_name",
    ]
    allowed = sorted(os.sched_getaffinity(0))
    assert len(allowed) >= 8
    os.sched_setaffinity(0, allowed[:8])
    def system_value(path):
        try:
            return Path(path).read_text().strip()
        except (PermissionError, FileNotFoundError) as error:
            if not path.startswith("/sys/"):
                raise
            return {"read_errno": error.errno}

    return {
        "platform": platform.uname()._asdict(),
        "prior_affinity": allowed,
        "affinity": sorted(os.sched_getaffinity(0)),
        "cpuinfo": Path("/proc/cpuinfo").read_text().split("\n\n")[0],
        "raw_system": {p: system_value(p) for p in paths},
    }


def qualify(tree, plain):
    assert (
        tree["mode"] == "tree"
        and plain["mode"] == "plain"
        and tree["source"] == plain["source"]
        and tree["programs"] == plain["programs"]
        and tree["old_programs"] == plain["old_programs"]
    )
    # Different rustc namespaces would be visible in the complete ELFs. File
    # locations and exact reread bytes are checked inside each install too.
    assert [[x["source"], x["program"]] for x in tree["cases"]] == [
        [x["source"], x["program"]] for x in plain["cases"]
    ]
    assert (
        tree["marker"]["missing"] == plain["marker"]["missing"]
        and tree["marker"]["examples_own_none"] == plain["marker"]["examples_own_none"]
    )
    assert sorted([n, m] for n, m, _ in tree["marker"]["emitted_real_flags"]) == sorted(
        [n, m] for n, m, _ in plain["marker"]["emitted_real_flags"]
    )
    slots = {}
    combined = {}
    for phase in ("edit", "repeat"):
        a, b = tree[phase], plain[phase]
        assert a["typed"] == b["typed"]
        t, u = a["native"], b["native"]
        assert set(t["examples"]) == set(ROLES["examples"]) and not u["examples"]
        rows = {
            "examples": [{"name": n, **r} for n, r in t["examples"].items()],
            "traced_whole": t["whole"],
            "untraced_whole": u["whole"],
        }
        slots[phase] = {
            "resolved": rows,
            "ceiling": ceiling.compute(rows),
            "library_excluded": t["library"],
        }
    for n in ROLES["examples"]:
        p, q = [
            next(x for x in slots[k]["resolved"]["examples"] if x["name"] == n)
            for k in ("edit", "repeat")
        ]
        combined[n] = {k: p[k] + q[k] for k in ("rustc_tree", "cc_tree", "wild_tree")}
    pair = {
        "examples": [{"name": n, **z} for n, z in combined.items()],
        **{
            k: sum(v["resolved"][k] for v in slots.values())
            for k in ("traced_whole", "untraced_whole")
        },
    }
    slots["edit_plus_first"] = {"resolved": pair, "ceiling": ceiling.compute(pair)}
    return slots


def main(position, pinned):
    assert (
        position in ROLES["orders"]
        and sha(HERE / "PLAN.md") == ROLES["plan_sha256"]
        and sha(HERE / "registration.json") == ROLES["original_registration_sha256"]
    )
    order = ROLES["orders"][position]
    root = Path(os.environ["RUNNER_TEMP"]) / "gnu-example-ceiling"
    root.mkdir()
    out = root / "receipt"
    out.mkdir()
    assert (
        root.is_absolute() and not root.is_symlink() and shutil.disk_usage(root).free > 12 * 2**30
    )
    try:
        save(out / "host.json", host())
        save(
            out / "enrollment.json",
            {
                "run": os.environ["GITHUB_RUN_ID"],
                "head": os.environ["GITHUB_SHA"],
                "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                "order": order,
                "position": position,
                "cli": w.CLI,
                "plan": sha(HERE / "PLAN.md"),
                "source": {f.name: sha(f) for f in HERE.iterdir() if f.is_file()},
            },
        )
        bins = pmu.compilers(root)
        save(
            out / "compiler.json",
            {
                "cc": subprocess.check_output(["cc", "--version"], text=True),
                "observer": sha(bins / "tree"),
                "loop": sha(bins / "loop"),
                "nested": sha(bins / "nested"),
                "plain": sha(bins / "plain"),
            },
        )
        store = out / "observers"
        store.mkdir()
        for n in ("tree", "plain", "loop", "nested"):
            shutil.copy2(bins / n, store / n)
        pmu.calibration(bins, out)
        print("28 entire command controls and nested positive + zero calibrated", flush=True)
        # These helpers read only the three exact released assets and the
        # source-qualified #301 Cargo. Credentials stay outside all Cargo calls.
        received = out / "custody"
        received.mkdir()
        donor = kit.acquire(root, received, pinned)
        del os.environ["GH_TOKEN"]
        (received / "cargo-301").rename(root / "cargo-301")
        src = w.source(root)
        kit.activate(root, donor, root / "cargo-301")
        env = w.env_for(root)
        seed = w.prepare_registry(root, src, env, out)
        (root / "sdk").rename(root / "ingress-sdk")
        (root / "slot").rename(root / "ingress-slot")
        answers = {}
        sdkids = []
        for mode in order:
            install = kit.activate(root, donor, root / "cargo-301")
            sdkids.append(install)
            save(out / (mode + "-activation.json"), install)
            env = w.env_for(root)
            assert set(env).isdisjoint(
                {
                    "RUSTFLAGS",
                    "RUSTC_WRAPPER",
                    "RUSTC_WORKSPACE_WRAPPER",
                    "CARGO_INCREMENTAL",
                    "CARGO_LOG",
                    "GITHUB_TOKEN",
                    "GH_TOKEN",
                    "CI",
                }
            )
            w.registry(env, seed)
            answers[mode] = w.run_arm(root, out / mode, bins, mode, src, env)
            (root / "sdk").rename(root / (mode + "-sdk"))
            (root / "slot").rename(root / (mode + "-slot"))
        assert (
            sdkids[0]["SDK_inode"] != sdkids[1]["SDK_inode"]
            and sdkids[0]["operational_tools"] == sdkids[1]["operational_tools"]
        )
        results = qualify(answers["tree"], answers["plain"])
        save(out / "qualified.json", results)
        print(
            "compiler-only ceiling",
            {k: v["ceiling"]["ideal_high"] for k, v in results.items()},
            flush=True,
        )
    except BaseException:
        (out / "refused.txt").write_text(traceback.format_exc())
        raise


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("position", choices=["01", "02"])
    ap.add_argument("signed_tools", type=Path)
    args = ap.parse_args()
    main(args.position, args.signed_tools.resolve())
