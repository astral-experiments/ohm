"""Reopen all original measurements and make only the registered hierarchical inferences."""

from fractions import Fraction
from math import comb
from pathlib import Path
from statistics import median
import json
import service as s
import collector as cc
import scoped

m = s.m


def stats(rows):
    assert len(rows)==8 and all(type(a)==type(b)==int and min(a,b)>0 for a,b in rows)
    ratios = [Fraction(b, a) for a, b in rows]
    speed = [1/q for q in ratios]
    above = sum(q > 2 for q in speed)
    below = sum(q < 2 for q in speed)
    n = above + below
    return dict(
        control_and_treatment=rows,
        paired_treatment_over_control=[float(v) for v in ratios],
        paired_median=float(median(ratios)),
        percent_reduction=100 * (1 - float(median(ratios))),
        paired_control_over_treatment=[float(v)for v in speed],median_speedup=float(median(speed)),
        half_medians_speedup=[float(median(speed[:4])),float(median(speed[4:]))],
        order_statistic_median_interval_99_21875_percent_speedup=[float(min(speed)),float(max(speed))],
        one_sided_sign_p_at_two=sum(comb(n, k) for k in range(above, n + 1)) / 2**n
        if n
        else 1,
        all_eight_strictly_above_2x=above==n==8 and all(median(v)>2 for v in (speed[:4],speed[4:])),
    )


def verify(out, meter, check_binary=False):
    panel = out / "native-22958"
    guards = m.read(panel / "all-native-guards.json")
    cal = m.read(out / "calibration.json")
    ready = cal["ready"]
    order = s.ORDERS
    assert (
        guards["independent"] == 16
        and guards["orders"] == list(order)
        and guards["boot"] == ready["boot"]
        and guards["case"] == s.case["registered"]
    )
    allocation = m.read(out / "boot-attestation.json")
    hosted_workspace = Path(allocation["workspace"])
    assert hosted_workspace.is_absolute() and ".." not in hosted_workspace.parts
    assert (
        allocation["boot"] == ready["boot"]
        and cal["unmultiplexed_calibration_clocks"] == 28
    )
    scoped.cal_raw(out / "per-rustc-calibration")
    observed_clock=m.read(out/"blocking-clock-pre/verified.json")
    assert observed_clock["boot"]==ready["boot"] and observed_clock["eligible_blocking_calibration"] and observed_clock["affinity"]==ready["affinity"]
    assert m.filesha(out/"blocking-clock-pre/verified.json")==allocation["blocking"]
    states = []
    cargo_lines=[]
    history = set()
    for i, rr in enumerate(order):
        data = {}
        windows = []
        for role in rr:
            d = panel / (str(i + 1) + "-" + role)
            seed = m.read(d / "seed.json")["sha256"]
            assert seed not in history
            history.add(seed)
            roster = m.read(d / "kernel-B/forms.json")
            selectors = {k: v[0] for k, v in roster.items()}
            assert set(selectors) == {"uv_client", "uv_configuration"} and all(
                len(v) == 1 for v in roster.values()
            )
            ctr = m.read(d / "native-before-score.json")
            assert ctr["same_seed"] and ctr["canonical"]
            material = m.read(d / "kernel-B/products.json")
            assert m.read(d / "bare-B/products.json") == material
            assert len(material["workspace"]) == 39 and {
                k: len(v) for k, v in material["externs"].items()
            } == {"uv_client": 64, "uv_configuration": 30}
            baseline = cc.streams(d / "kernel-B")
            assert baseline == cc.streams(d / "bare-B")
            visits=m.read(d/"visit-order.json")
            assert [x[0] for x in visits]==["wall","whole","threads"] and all(x[1]<x[2]for x in visits) and all(a[2]<=b[1]for a,b in zip(visits,visits[1:]))
            own = {}
            for mode in ("wall", "whole", "threads"):
                v = d / mode
                flag = m.read(v / "verified.json")
                assert (
                    flag["seed"] == seed
                    and flag["source"] == s.case["B"]
                    and flag["boot"] == ready["boot"]
                    and flag["same_seed"]
                )
                assert (
                    cc.streams(v) == baseline
                    and m.read(v / "products.json") == material
                    and flag["measured"] == m.filesha(v / "products.json")
                )
                q = m.read(v / "native/witness.json")
                assert q["codes"]["schema"] == [0, []] and q["codes"][
                    "client-negative"
                ] == [1, ["E0308"]]
                if mode == "threads":
                    req = m.read(d / "scoped-request.json")
                    assert (
                        req["command"] == s.CHECK
                        and req["selectors"] == selectors
                        and req["cwd"] == str(m.SRC)
                        and req["environment"] == m.ENV
                    )
                    nums = scoped.read(v, req)
                    assert nums == m.read(v / "counts.json") and set(nums) == set(
                        selectors
                    )
                    own.update(nums)
                    own["sum_two"] = sum(nums.values())
                    continue
                q = m.read(v / "ordinary.json")
                assert (
                    q["boot"] == ready["boot"]
                    and q["cpus"] == ready["affinity"]
                    and q["argv"] == s.CHECK
                    and q["exit"] == 0
                    and q["env"] == m.ENV
                )
                assert q["end_ns"] - q["start_ns"] == q["ns"] > 0
                span,=[v for v in visits if v[0]==mode]
                assert span[1]<=q["start_ns"]<q["end_ns"]<=span[2]
                windows.append((q["start_ns"], q["end_ns"], role, mode))
                if mode == "whole":
                    assert (
                        q["invoked"]
                        == [
                            ready["plain"],
                            str(
                                hosted_workspace
                                / "trait-results"
                                / v.relative_to(out)
                                / "whole-clock.json"
                            ),
                            *s.CHECK,
                        ]
                        and q["mode"] == "pmu"
                    )
                    lc = meter.clock(v / "whole-clock.json", 0)
                    assert lc["running"] == lc["enabled"] > 0
                    own[mode] = lc["instructions"]
                else:
                    assert q["mode"] == "native" and q["invoked"] == s.CHECK and q["wait"]=="os.waitpid(child.pid, 0)" and type(q["pid"])==int and q["pid"]>0
                    finished,=[line for line in (v/"cargo.stderr").read_text().splitlines() if line.startswith("    Finished `dev` profile [unoptimized + debuginfo] target(s) in ")]
                    cargo_lines.append(dict(pair=i+1,role=role,finished=finished,stderr_sha256=m.filesha(v/"cargo.stderr"),blocking_ns=q["ns"]))
                    own[mode] = q["ns"]
            data[role] = own
        by = sorted(windows)
        assert all(a[1] <= b[0] for a, b in zip(by, by[1:])) and list(
            dict.fromkeys(x[2] for x in by)
        ) == list(rr)
        states.append(data)
    metrics = {}
    for key in ("uv_client", "sum_two", "uv_configuration", "whole", "wall"):
        metrics[key] = stats([[x[s.ROLES[0]][key], x[s.ROLES[1]][key]] for x in states])
    primary = metrics["wall"]["all_eight_strictly_above_2x"]
    return dict(
        complete=True,
        actual_signed_Cargo=s.CHECK,
        sources=s.SOURCES,
        boot=ready["boot"],
        metrics=metrics,
        primary_wall_twofold_all_eight=primary,
        observed_Cargo_Finished_lines=cargo_lines,
        original_exact_cold_gate_redeemed=False,
        independent_histories=len(history),
        registered=s.case["registered"],
        release_lock=m.filesha(s.HERE/"release-lock.json"),
        scope="Eight-pair ordinary blocking wall primary with separately restored userspace whole-Cargo and thread-group counters. The comparison covers the complete compiler stacks.",
    )


def close(out):
    w, tmp, _ = s.host()
    _, meter = m.pmu(w, tmp)
    z = verify(out, meter)
    m.save(out / "native-22958/score.json", z)
    print(json.dumps(z, sort_keys=True))
