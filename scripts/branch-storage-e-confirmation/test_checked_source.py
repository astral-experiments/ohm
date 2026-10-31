"""The historical and corrected Rust qualifications cannot authenticate one another."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checked_source as c
import confirm_binding


class CorrectedSource(unittest.TestCase):
    def test_boot_seal(self):
        _, prior, excluded = confirm_binding.local()
        self.assertEqual(len(prior["hosts"]), 12)
        self.assertEqual(len(excluded), 66)

    def test_historical_source_is_not_admitted(self):
        old = HERE.parent / "branch-first-session-e-screen/inputs"
        with self.assertRaisesRegex(ValueError, "different corrected source enrollment"):
            c.validate(json.loads((old / "e-source.json").read_bytes()),
                       json.loads((old / "source-replay.json").read_bytes()))

    def test_source_seal(self):
        if c.REG_SHA is None or c.CERT_SHA is None:
            with self.assertRaisesRegex(ValueError, "unsealed corrected E"):
                c.enrollment()
            return
        reg = json.loads(c.RUNTIME.read_bytes())
        proof = json.loads(c.CERTIFICATE.read_bytes())
        self.assertEqual(c.enrollment(), reg["source"])
        good = proof["checked_cases"]["corrected"]["cargo"]
        for mutate in (
            lambda e, p: e["source"].update(head="0" * 40),
            lambda e, p: e["source"].update(run=41242405382),
            lambda e, p: e["source"].update(attempt=2),
            lambda e, p: p["source"].update(tree="0" * 40),
            lambda e, p: p["restored"]["driver"].__setitem__(0, c.HISTORICAL),
            lambda e, p: p.update(separate_inodes=80),
            lambda e, p: p["cross_readers"].pop("E-cold-A-to-K"),
            lambda e, p: p["tests"]["run_make"].pop(),
            lambda e, p: p["checked_cases"]["old"]["cargo"].update({"B-conflicting-raw":good["B-conflicting-raw"]}),
            lambda e, p: p["checked_cases"]["corrected"]["cargo"]["B-conflicting-raw"].update(marker=True),
            lambda e, p: p["checked_cases"]["corrected"]["mixed"].update({"conflict-read-B":"0" * 64}),
            lambda e, p: p["checked_cases"]["corrected"]["F_bridge"].update({"read-B83":"0" * 64}),
            lambda e, p: p["checked_cases"]["corrected"]["cargo"]["B-raw-only-old"].update(value=29),
            lambda e, p: p["collision"]["roles"]["corrected"].update(driver=c.HISTORICAL),
        ):
            e, p = deepcopy(reg), deepcopy(proof)
            mutate(e, p)
            with self.assertRaises((ValueError, KeyError)):
                c.validate(e, p)


if __name__ == "__main__":
    unittest.main()
