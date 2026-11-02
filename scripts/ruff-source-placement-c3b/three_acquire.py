"""Run six fixed chronological blocks, each with the three actual ordinary toolchains."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exact_stats
import footer
import scope
from three_kit import ThreeRuntime, INTERNAL
import worker as original


def main():
    slot = int(sys.argv[1])
    sources = {
        n: Path(v).resolve(strict=True)
        for n, v in zip(("option", "e2e"), sys.argv[2:], strict=True)
    }
    study = scope.bind()
    exact_stats.registered(study)
    assignment = study["blocks"][slot - 1]
    scope.base.need(assignment["slot"] == slot, "unknown scheduled block")
    order = [INTERNAL[r] for r in assignment["roles"]]
    inputs = Path(os.environ["RUNNER_TEMP"]) / "placement-qualified-sdks"
    older = inputs.with_name("placement-previous-sdks")
    gate = json.loads((inputs / "native-gate.json").read_bytes())
    live_boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    scope.base.need(
        live_boot not in {r["boot"] for r in gate["admissions"].values()}
        and gate["protocol"] == scope.base.sha(scope.HERE / "three-arm-protocol.json")
        and set(gate["admissions"]) == {"option", "e2e"},
        "separate new real boot and native admission required",
    )
    run_dir, evidence, _ = original.census.paths()
    run_dir.mkdir()
    evidence.mkdir()
    out = evidence / "physical"
    out.mkdir()
    root = run_dir / "actual-ruff"
    root.mkdir()
    for name in ("workproduct-indices", "native-bodies", "owner-archives"):
        (out / name).mkdir()
    for pre, kit in (("", inputs), ("C2-", older)):
        for name in ("source-qualification.json", "docs-qualification.json"):
            shutil.copyfile(kit / name, out / (pre + name))
        for r in ("P", "C"):
            shutil.copyfile(kit / "capsule" / (r + ".json"), out / (pre + r + "-source-kit.json"))
    shutil.copyfile(inputs / "native-gate.json", out / "previous-gate.json")
    with scope.product("C3b") as reg, ExitStack() as stack:
        stack.enter_context(patch.object(original.transport, "BRANCH", scope.BRANCH))
        stack.enter_context(
            patch.object(
                original.runtime,
                "Runtime",
                lambda work, inp, o, tools: ThreeRuntime(work, inp, o, tools, older),
            )
        )
        cpus, kit = original.setup(root, out, inputs)
        need = scope.base.need
        need(
            all(
                kit.refs[r][name]["sha"] == gate["kits"][r][name]
                for r in ("P", "C")
                for name in gate["kits"][r]
            ),
            "physical compilers differ from previously admitted ones",
        )
        origins = {
            tag: json.loads((kitdir / "source-qualification.json").read_bytes())
            for tag, kitdir in (("C3b", inputs), ("C2", older))
        }
        need(
            live_boot not in {p["seal"]["boot"] for p in origins.values()},
            "compiler construction boot reused",
        )
        entry = {
            "schema": "three-physical-bootstrap-qualified",
            "run": int(os.environ["GITHUB_RUN_ID"]),
            "qa": os.environ["GITHUB_SHA"],
            "boot": live_boot,
            "cpus": cpus,
            "slot": slot,
            "assignment": assignment,
            "internal_order": order,
            "suites": assignment["suites"],
            "sources": study["source"],
            "accepted": scope.base.sha(out / "previous-gate.json"),
            "factory": {tag: p["factory_run"] for tag, p in origins.items()},
            "products": {tag: p["seal"]["sha256"] for tag, p in origins.items()},
            "counter_sha": scope.base.sha(kit.tools / "count"),
            "protocol": scope.base.sha(scope.HERE / "three-arm-protocol.json"),
        }
        scope.base.save(out / "entry.json", entry)
        operation = original.acquire.phase

        def recorded(
            kit, where, work, repo, env, which, suite, graph, cmd, extras, gold, score, opens, admit
        ):
            need(not opens and not admit, "native observer entered scored history")
            with original.placement_peak.observe(original.guards, where, kit, owners=()):
                actual = operation(
                    kit,
                    where,
                    work,
                    repo,
                    env,
                    which,
                    suite,
                    graph,
                    cmd,
                    extras,
                    gold,
                    score,
                    opens,
                    admit,
                )
            version = 3 if kit.active == "C" else 1
            with patch.object(original.storage, "parse_footer", lambda b: footer.parse(b, version)):
                original.projections(kit, actual, where, work, "score", which, suite)
            return actual

        stack.enter_context(patch.object(original.acquire, "phase", recorded))
        reports = {}
        for name in assignment["suites"]:
            reports[name] = original.acquire.suite_run(
                kit, root, sources[name], name, "score", order
            )
            cross = json.loads((out / name / "cross-role.json").read_bytes())
            need(
                set(cross["shards"]) == set(INTERNAL.values())
                and len({tuple(ls) for ls in cross["shards"].values()}) == 3
                and all(len(ls) == 1 for ls in cross["shards"].values()),
                "not three stable actual Cargo/compiler identities",
            )
        kit.finish()
        scope.base.save(
            out / "complete.json",
            {
                "entry": scope.base.sha(out / "entry.json"),
                "physical": scope.base.sha(out / "physical-roles.json"),
                "reports": reports,
                "sources": study["source"],
                "previous_gate": entry["accepted"],
                "kinds": INTERNAL,
                "scope": "Each original cold/changed/unchanged Cargo process and all descendants. Every source checksum and raw phase are separate.",
            },
        )


if __name__ == "__main__":
    main()
