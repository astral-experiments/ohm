"""Exercise the two orders, whole clocks, original identities and six-slot decision."""

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from uuid import UUID

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import endpoints
import packed_sdk as sdk
import packed_confirmation as six


def originals():
    raw = gzip.decompress(
        (HERE / "inputs/excluded-contact-clock-control.json.gz").read_bytes()
    )
    assert (
        hashlib.sha256(raw).hexdigest()
        == "c35de4e9f9fa75a3c7f86f792dac70b9d3c5ee79b611a9857af1a9bf580a72e6"
    )
    data = json.loads(raw)
    assert data["original"] == six.CONTACT_ORIGINAL and len(data["members"]) == 19
    return {k: json.loads(v) for k, v in data["members"].items()}


def clocks(slot):
    raw = originals()
    # For the reverse-order unit case, move the two real time sequences between synthetic
    # slot labels. The native contact remains an excluded D-then-Q observation.
    groups = {}
    for role, actual in zip(six.order(slot), sdk.ARMS, strict=True):
        groups[role] = {
            phase: raw[f"measured-return-{actual}/{phase}/clock.json"]
            for phase in endpoints.PHASES
        }
    sums = {a: endpoints.count(v) for a, v in groups.items()}
    bounds = []
    for i, (lane, line) in enumerate(six.LANES):
        for j, a in enumerate(six.order(slot)):
            if lane == "measured":
                rows = sums[a]["phases"]
                start, stop = rows["Y-B"]["start"] - 1, rows["repair"]["stop"] + 1
            else:
                start = 100 * (2 * i + j + 1)
                stop = start + 1
            bounds.append(
                dict(lane=lane, line=line, arm=a, start_ns=start, stop_ns=stop)
            )
    return groups, sums, bounds


def hosts_and_reports():
    hosts, reports = {}, {}
    for n, pos in enumerate(six.POSITIONS, 1):
        hosts[pos] = dict(
            position=pos,
            run=9999001,
            head="1" * 40,
            job=998100 + n,
            runner=f"six-new-{n}",
            runner_id=99100 + n,
            artifact=988100 + n,
            bytes=1234,
            position_sha256=hashlib.sha256(("position" + pos).encode()).hexdigest(),
            sha256=hashlib.sha256(("archive" + pos).encode()).hexdigest(),
            boot=str(UUID(int=10**9 + n)),
            order=list(six.order(pos)),
        )
        raw, sums, bounds = clocks(pos)
        for role, value in (("Don", 600 + n), ("Qon", 200)):
            raw[role]["X-B"]["instructions"] = value
            sums[role] = endpoints.count(raw[role])
        reports[pos] = dict(
            official=dict(hosts[pos], attempt=1),
            qualified=True,
            boot=hosts[pos]["boot"],
            source=sdk.enrolled(),
            visits=46,
            metered=14,
            traced=16,
            histories=bounds,
            raw_clocks=raw,
            measured=sums,
            primary={a: sums[a]["phases"]["X-B"]["instructions"] for a in sdk.ARMS},
        )
    return hosts, reports


class Six(unittest.TestCase):
    def test_exact_contact_native_and_exclusion(self):
        rows = originals()
        pos = rows["position.json"]
        self.assertEqual(
            (pos["run"], pos["head"], pos["order"]),
            (six.CONTACT, six.CONTACT_HEAD, ["Don", "Qon"]),
        )
        with self.assertRaises(ValueError):
            six.fresh(pos["boot"], pos["runner"])
        for r in sdk.ARMS:
            side = "X" if r == "Don" else "Y"
            for history in ("return", "dirty"):
                sel = rows[f"structural-{history}-{r}/X-B/donor-selected.json"]
                self.assertEqual(set(sel), {"ruff_python_ast", "ruff_python_edits"})
                for files in sel.values():
                    self.assertEqual(
                        set(files), {side + "/dep-graph.bin", side + "/query-cache.bin"}
                    )
                    self.assertTrue(
                        all(
                            row["ino"] > 0 and row["length"] > 0 and row["pid"] > 0
                            for v in files.values()
                            for row in v
                        )
                    )

    def test_all_concurrent_original_identities_are_excluded(self):
        other = sdk.read(HERE / "inputs/six-default-identities.json")["positions"]
        live = sdk.read(HERE / "inputs/six-live-namespaces.json")["prior"]
        previous = six.frozen()
        self.assertEqual(len(other), 4)
        for row in other.values():
            with self.assertRaises(ValueError):
                six.fresh(row["boot"], "genuinely-different-new-runner")
        for row in live:
            self.assertIn(row["job"], previous["jobs"])
            with self.assertRaises(ValueError):
                six.fresh(str(UUID(int=10**9)), row["runner"])

    def test_both_physical_and_ordinary_orders(self):
        for slot in six.POSITIONS:
            raw, summary, h = clocks(slot)
            six.check_clocks(raw, summary)
            six.history_order(slot, h, summary)
            for key in (0, 2, 4, 6):
                wrong = h.copy()
                wrong[key : key + 2] = reversed(wrong[key : key + 2])
                with self.assertRaises(ValueError):
                    six.history_order(slot, wrong, summary)
            other = deepcopy(h)
            other[-1]["stop_ns"] = summary[six.order(slot)[-1]]["phases"]["repair"][
                "stop"
            ]
            with self.assertRaises(ValueError):
                six.history_order(slot, other, summary)

    def test_raw_hardware_cpu_and_failed_command(self):
        for key, value in (
            ("running", 0),
            ("user_us", -1),
            ("system_us", -1),
            ("code", 0),
            ("instructions", 0),
        ):
            raw, summary, _ = clocks("01")
            raw["Don"]["invalid"][key] = value
            with self.assertRaises(ValueError):
                six.check_clocks(raw, summary)
        raw, summary, _ = clocks("01")
        raw["Qon"]["X-B"].update(running=999, enabled=1000)
        with self.assertRaises(ValueError):
            six.check_clocks(raw, summary)
        raw, summary, _ = clocks("02")
        summary["Don"]["whole7"]["instructions"] += 1
        with self.assertRaises(ValueError):
            six.check_clocks(raw, summary)

    def test_no_replacement_and_unconditional_denominator(self):
        hs, rs = hosts_and_reports()
        result = six.evaluate(rs, hs)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["interval"], [[601, 200], [303, 100]])
        self.assertEqual(result["median"], [1207, 400])
        self.assertEqual(result["one_sided_sign_tail"], [1, 64])
        self.assertEqual(result["coverage"], [31, 32])
        for k, prior in six.IDENTITIES.items():
            for bad in [hs["02"][k], six.frozen()[prior][0]]:
                changed = deepcopy(hs)
                changed["01"][k] = bad
                with self.assertRaises(ValueError):
                    six.check_hosts(changed)
        bad = deepcopy(hs)
        bad["03"]["order"].reverse()
        with self.assertRaises(ValueError):
            six.check_hosts(bad)
        with self.assertRaises(ValueError):
            six.evaluate({p: v for p, v in rs.items() if p != "06"}, hs)
        with self.assertRaises(ValueError):
            six.evaluate(rs, {p: v for p, v in hs.items() if p != "06"})
        for k in ("qualified", "metered", "traced", "visits", "boot"):
            bad = deepcopy(rs)
            bad["04"][k] = False
            with self.assertRaises(ValueError):
                six.evaluate(bad, hs)
        selected = rs["04"]
        ident = selected["raw_clocks"]["Don"]["X-B"]
        ident["instructions"] = 400
        selected["primary"]["Don"] = 400
        selected["measured"]["Don"] = endpoints.count(selected["raw_clocks"]["Don"])
        self.assertFalse(six.evaluate(rs, hs)["accepted"])
        self.assertEqual(six.evaluate(rs, hs)["wins"], 5)

    def test_prior_contact_and_substituted_registration(self):
        hs, _ = hosts_and_reports()
        h = hs["01"]
        real = originals()["position.json"]
        with self.assertRaises(ValueError):
            six.position_record(real, h)
        reg = {
            **real,
            **six.ENROLLMENT,
            **{k: h[k] for k in ("position", "order", "run", "head", "boot", "runner")},
            "mode": six.MODE,
        }
        six.position_record(reg, h)
        for k in (
            *six.ENROLLMENT,
            "mode",
            "position",
            "order",
            "run",
            "head",
            "runner",
            "boot",
        ):
            bad = dict(reg)
            bad[k] = None
            with self.assertRaises(ValueError):
                six.position_record(bad, h)

    def test_official_closed_source_and_substituted_bytes(self):
        hosts, _ = hosts_and_reports()
        rid = hosts["01"]["run"]
        head = hosts["01"]["head"]
        repo = {"id": 562061, "full_name": "astral-experiments/ohm"}
        run = dict(
            id=rid,
            run_attempt=1,
            head_sha=head,
            head_branch=six.BRANCH,
            event="workflow_dispatch",
            path=".github/workflows/ci.yml",
            status="completed",
            conclusion="success",
            repository=repo,
            head_repository=repo,
        )
        jobs, assets, early = [], [], {}
        body = b"fixture original for official six-identity guards"
        for pos, h in hosts.items():
            h["sha256"] = hashlib.sha256(body + pos.encode()).hexdigest()
            h["bytes"] = len(body) + 2
            jobs.append(
                dict(
                    id=h["job"],
                    name=six.LABEL + pos,
                    run_id=rid,
                    run_attempt=1,
                    head_sha=head,
                    head_branch=six.BRANCH,
                    status="completed",
                    conclusion="success",
                    labels=["namespace-profile-ubuntu-24-04-16"],
                    runner_name=h["runner"],
                    runner_id=h["runner_id"],
                    steps=[
                        dict(name=n, status="completed", conclusion="success")
                        for n in six.REQUIRED_STEPS
                    ],
                )
            )
            assets.append(
                dict(
                    id=h["artifact"],
                    name=six.ARTIFACT + pos,
                    size_in_bytes=h["bytes"],
                    digest="sha256:" + h["sha256"],
                    expired=False,
                    workflow_run=dict(
                        id=rid,
                        head_sha=head,
                        head_branch=six.BRANCH,
                        repository_id=repo["id"],
                        head_repository_id=repo["id"],
                    ),
                )
            )
            early[pos] = dict(job=h["job"], order=h["order"])
        values = {
            "run": run,
            "jobs": dict(total_count=6, jobs=jobs),
            "artifacts": dict(total_count=6, artifacts=assets),
            "pre-outcome": dict(
                run=rid,
                head=head,
                assets=0,
                attempt=1,
                positions=early,
                outcome_members_opened=0,
            ),
            "boot-admission": dict(
                run=rid,
                head=head,
                admitted=True,
                outcomes_opened=0,
                reason=None,
                missing=[],
                hosts=hosts,
            ),
        }
        with TemporaryDirectory() as temp:
            d = Path(temp)

            def write(current):
                for name, data in current.items():
                    (d / (name + ".json")).write_text(json.dumps(data))

            write(values)
            original = d / "control.zip"
            original.write_bytes(body + b"02")
            self.assertEqual(
                six.official(d, original, head, "02"), dict(hosts["02"], attempt=1)
            )
            original.write_bytes(body + b"01")
            with self.assertRaises(ValueError):
                six.official(d, original, head, "02")
            original.write_bytes(body + b"02")
            for key in ("jobs", "artifacts", "pre-outcome", "boot-admission", "run"):
                bad = deepcopy(values)
                if key == "jobs":
                    bad[key]["jobs"][1]["steps"] = []
                if key == "artifacts":
                    bad[key]["artifacts"][5]["workflow_run"]["head_sha"] = "0" * 40
                if key == "pre-outcome":
                    bad[key]["assets"] = 1
                if key == "boot-admission":
                    bad[key]["outcomes_opened"] = 1
                if key == "run":
                    bad[key]["head_repository"]["full_name"] = "elsewhere"
                write(bad)
                with self.assertRaises(ValueError):
                    six.official(d, original, head, "02")


if __name__ == "__main__":
    unittest.main()
