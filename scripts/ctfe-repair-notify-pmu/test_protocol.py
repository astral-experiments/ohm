import copy
import json
from pathlib import Path
import stat
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import protocol as p
import storage
import notify_calibration


def synthetic_contact():
    return dict(
        run=p.CONTACT_RUN,
        head=p.CONTACT_HEAD,
        job=p.CONTACT_JOB,
        runner=p.CONTACT_RUNNER,
        boot="00000000-0000-4000-8000-000000000000",
        artifact=1234,
        bytes=123456,
        sha256="1" * 64,
        independent_sha256="2" * 64,
    )


def clock(n, ix):
    return dict(
        start=1 + ix * 100,
        stop=50 + ix * 100,
        user_us=1,
        system_us=0,
        instructions=n,
        enabled=70,
        running=70,
        event_errno=0,
        code=0,
    )


def admitted():
    contact = synthetic_contact()
    totals = dict(E=100, O=150, P=153, B=127)
    return {
        pos: dict(
            run=1,
            attempt=1,
            job=int(pos),
            boot=f"10000000-0000-4000-8000-0000000000{pos}",
            runner="nsc-runner-test" + pos,
            position=pos,
            order=list(order),
            complete=True,
            issues=[],
            calibration=True,
            products=True,
            publication=True,
            separate_native_role="E" if pos == "01" else "O",
            contact=contact,
            repairs={arm: clock(totals[arm], i) for i, arm in enumerate(order)},
        )
        for pos, order in p.ARMS.items()
    }


class Cases(unittest.TestCase):
    def test_counterbalanced_four_arms_and_boundaries(self):
        rows = admitted()
        out = p.paired(rows, synthetic_contact(), set())
        self.assertTrue(out["both_hosts_meet_all_diagnostic_criteria"])
        r = out["boot_results"]["01"]
        self.assertEqual(
            r["signed"],
            dict(
                ordinary_candidate_minus_parent=50,
                pass_minus_block=26,
                pass_minus_ordinary_candidate=3,
                ordinary_excess_minus_intervention=24,
            ),
        )
        self.assertEqual(r["ratios"]["intervention_over_contemporaneous_excess"], p.ratio(26, 50))
        self.assertEqual(p.ARMS["01"], p.ARMS["02"][::-1])
        for b, accepted in [(128, True), (129, False)]:
            rows["01"]["repairs"]["B"]["instructions"] = b
            self.assertEqual(
                p.paired(rows, synthetic_contact(), set())["both_hosts_meet_all_diagnostic_criteria"],
                accepted,
            )
        rows["01"]["repairs"]["P"]["instructions"] = 154
        self.assertFalse(
            p.paired(rows, synthetic_contact(), set())["both_hosts_meet_all_diagnostic_criteria"]
        )

    def test_signed_and_unbounded_ratios(self):
        r = p.contrasts(dict(E=80, O=60, P=66, B=95))
        self.assertEqual(r["signed"]["ordinary_candidate_minus_parent"], -20)
        self.assertEqual(r["signed"]["pass_minus_block"], -29)
        self.assertIsNone(r["ratios"]["intervention_over_contemporaneous_excess"])
        r = p.contrasts(dict(E=80, O=100, P=110, B=30))
        self.assertEqual(r["ratios"]["intervention_over_contemporaneous_excess"], p.ratio(80, 20))
        self.assertEqual(r["signed"]["ordinary_excess_minus_intervention"], -60)

    def test_no_rows_after_any_refusal(self):
        for mutate in [
            lambda x: x.pop("02"),
            lambda x: x["01"].update(complete=False),
            lambda x: x["02"].update(calibration=False),
            lambda x: x["02"].update(products=False),
            lambda x: x["02"].update(publication=False),
            lambda x: x["01"].update(issues=["unmatched actual Wild"]),
            lambda x: x["02"]["repairs"]["B"].update(running=69),
            lambda x: x["02"]["repairs"]["B"].update(instructions=True),
            lambda x: x["02"]["repairs"]["P"].update(start=50),
            lambda x: x["02"]["repairs"].pop("B"),
            lambda x: x["02"].update(order=list("EOPB")),
            lambda x: x["01"].update(separate_native_role="O"),
            lambda x: x["01"].update(boot=x["02"]["boot"]),
            lambda x: x["01"].update(runner=x["02"]["runner"]),
            lambda x: x["01"].update(job=x["02"]["job"]),
            lambda x: x["01"].update(run=2),
            lambda x: x["02"].update(contact={**x["02"]["contact"], "artifact": 1}),
        ]:
            rows = admitted()
            mutate(rows)
            with self.assertRaises(ValueError):
                p.paired(rows, synthetic_contact(), set())
        for registry in [
            None,
            {},
            dict(failed=True),
            {**synthetic_contact(), "independent_sha256": "0" * 64},
        ]:
            with self.assertRaises(ValueError):
                p.paired(admitted(), registry, set())

    def test_history_is_the_original_normal_command(self):
        sys.path.insert(0, str(p.FROZEN))
        import read_contact

        self.assertEqual(list(p.CARGO), read_contact.old.CARGO)
        root = Path("/work/a")
        sdk = root / "home/.rustup/toolchains/ohm"
        for mode in "EOPB":
            where = root / "logs" / ("return-" + mode) / "repair"
            cmd = p.launches(mode, root, where, sdk)
            plain = str(root / "logs/observers/plain")
            self.assertEqual(cmd[cmd.index(plain) :], [plain, str(where / "clock.json"), *p.CARGO])
            self.assertEqual(cmd[0] == plain, mode in "EO")
            if mode in "PB":
                self.assertEqual(
                    cmd[:5],
                    [
                        str(root / "logs/tools/table-notify"),
                        str(where / "calls"),
                        str(sdk),
                        str(where / "calls/notify.status"),
                        "--",
                    ],
                )
            self.assertNotIn("observe", cmd)

    def test_sorted_json_object_does_not_replace_physical_order(self):
        rows = json.loads(json.dumps(admitted(), sort_keys=True))
        self.assertTrue(
            p.paired(rows, synthetic_contact(), set())["both_hosts_meet_all_diagnostic_criteria"]
        )
        rows["01"]["repairs"]["E"], rows["01"]["repairs"]["O"] = (
            rows["01"]["repairs"]["O"],
            rows["01"]["repairs"]["E"],
        )
        with self.assertRaises(ValueError):
            p.paired(rows, synthetic_contact(), set())

    def test_actual_counter_abi_and_nested_process_slopes(self):
        for mode in ("P", "B"):
            rows = [
                dict(
                    loop=n,
                    arg_mode="1",
                    copies=2,
                    status=0,
                    source=mode,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    listener=[0, 0, 2, 0, 0],
                    clock=clock(20000 + 4 * n, i),
                )
                for i, n in enumerate(notify_calibration.SIZES)
            ]
            self.assertEqual(
                notify_calibration.parse(rows, mode), [[16000000, 16000000], [48000000, 48000000]]
            )
            for mutation in [
                lambda r: r[1]["clock"].update(instructions=4_020_000),
                lambda r: r[3]["clock"].update(enabled=71),
                lambda r: r[1].update(listener=[0, 0, 2, 2, 0]),
                lambda r: r[0].update(source="wrong"),
            ]:
                altered = copy.deepcopy(rows)
                mutation(altered)
                with self.assertRaises(ValueError):
                    notify_calibration.parse(altered, mode)

    def test_count_window_distinguishes_cargo_and_live_orphan(self):
        # Structural order projection only. A complete schema-3 parse is an independent prerequisite.
        argv = b"/x/bin/cargo".hex().encode()
        raw = (
            b"R\t1\t88\nE\t1\t1\t88\t88\t1\t00\t00\t"
            + argv
            + b"\t00\nB\t2\t89\t88\nB\t3\t90\t90\nX\t3\t90\t0\nT\t3\t90\t0\nX\t1\t88\t0\nT\t1\t88\t0\nX\t2\t89\t0\nT\t2\t89\t0\n"
        )
        self.assertEqual(
            p.completion(raw), dict(cargo_generation=1, closed=3, noncargo_before_cargo_reap=1)
        )
        late = raw.replace(b"X\t3\t90\t0\n", b"") + b"X\t3\t90\t0\n"
        for alt in [late, raw.replace(b"T\t2\t89\t0\n", b""), raw.replace(argv, b"2f62696e2f636174")]:
            with self.assertRaises(ValueError):
                p.completion(alt)

    def test_parent_object_comparison_distinguishes_representations_from_code(self):
        def rows(names):
            return {
                "owner": {
                    "objects": {
                        key: {"digest": digest, "bytes": size, "packed": packed}
                        for key, digest, size, packed in names
                    }
                }
            }

        parent = rows([("same", "a", 5, False), ("changed", "b", 3, False), ("removed", "e", 4, False)])
        candidate = rows([("same", "a", 5, True), ("changed", "c", 3, False), ("added", "d", 9, False)])
        actual = storage.parent_objects(parent, candidate, {"packed_raw_objects": {"owner": (1, 2)}})
        self.assertEqual(
            actual["owner"],
            {
                "same_native_bodies": 1,
                "different_native_bodies": ["changed"],
                "parent_only": ["removed"],
                "candidate_only": ["added"],
                "representation_changes": 1,
            },
        )
        with self.assertRaises(ValueError):
            storage.parent_objects(parent, {}, {"packed_raw_objects": {"owner": (1, 2)}})

    def test_storage_dedup_regular_and_cross_root(self):
        mode = stat.S_IFREG | 0o444
        r = [1, 3, 3, mode, 16, 7001]
        q = {
            "build/r/dep-graph.bin": r,
            "target/s/ohm-build-dep-graph.bin": r,
            "target/a.o": [1, 4, 1, mode, 8, 500],
        }
        a = storage.allocation(q, 24 * 512)
        self.assertEqual(a["unique_inodes"], 2)
        self.assertEqual(a["allocated_by_name_class"], {"raw-dep-graph": 8192, "raw-objects": 4096})
        self.assertEqual(a["allocated_by_visibility"], {"build+target": 8192, "target": 4096})
        for k, row in [("target/s/new", [1, 3, 3, mode, 8, 7001]), ("build/../bad", r)]:
            with self.assertRaises(ValueError):
                storage.allocation(dict(q, **{k: row}), 24 * 512)


if __name__ == "__main__":
    unittest.main()
