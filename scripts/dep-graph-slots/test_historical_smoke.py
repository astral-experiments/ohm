"""Replay the historical GNU and Darwin Bash originals from run 41316183280, attempt 1."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from release_smoke import historical_marked_refusal

# Complete original ZIP and slot-link-smoke/historical.log, independently hashed.
ORIGINALS = {
    "13086994788": ("01be083b2d66967ed7ce0248063965ccf4a22332b0876130a787e85d985d617f",
                    "261cb1762bc7c9e87a5cf24cbc0660dc4add81316079a11406c84fa94845cdcb"),
    "13090420906": ("1b178dc240ad307b04c4e1da26b150ea6a13dd3bca77ff383692a71dd715aabf",
                    "5d4f3d4cac436d61066c718b0d9c50a93162ae58a8409e8e87807fe2569e58c8"),
}
SCRIPT = HERE / "release-22/smoke-test-relink.sh"
EVENTS = b"link\nlink\n"  # The new worker will escrow this independently of wc's text.


class TestHistoricalScope(unittest.TestCase):
    def test_real_output_linker_records(self):
        # Derive the real output-counting relay from the frozen, unmodified coordinator.
        body = SCRIPT.read_text().split("cat >count-links <<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            relay, source, events = (root / name for name in ("count-links", "answer.c", "links"))
            relay.write_text(body + "\n")
            relay.chmod(0o700)
            source.write_text('#include <stdio.h>\nint main(void) { return puts("17") < 0; }\n')
            env = dict(os.environ, OHM_SMOKE_LINK_LOG=str(events))
            for name in ("first", "second"):
                exe = root / name
                subprocess.run([relay, source, "-o", exe], env=env, check=True)
                self.assertEqual(subprocess.check_output([exe]), b"17\n")
            self.assertEqual(events.read_bytes(), EVENTS)

    def test_originals_and_refusals(self):
        records = json.loads(gzip.decompress((HERE / "historical-link-traces.json.gz").read_bytes()))
        self.assertEqual(set(records), set(ORIGINALS))
        for artifact, row in records.items():
            with self.subTest(artifact=artifact):
                text = row["text"]
                self.assertEqual((row["zip_sha256"], hashlib.sha256(text.encode()).hexdigest()), ORIGINALS[artifact])

                def check(raw=text, events=EVENTS, script=SCRIPT, label="historical", code=1):
                    return historical_marked_refusal(script, label, code, raw, Path(row["project"]), events)

                self.assertTrue(check())
                diagnostic = text.splitlines()[-2]
                prefix = "Expected 0 linker calls for two executables returning 17, observed"
                self.assertTrue(check(text.replace(diagnostic, prefix + "\t 2\t")))
                for wrong in ("20", "12", "02", "1", "2 2", "2 junk", "\n2", "\v2", "٢"):
                    self.assertFalse(check(text.replace(diagnostic, prefix + " " + wrong)), wrong)
                for wrong in ("published-22", "cargo-only", "rebased", "historical-undeclared"):
                    self.assertFalse(check(label=wrong), wrong)
                for code in (0, 2, 101):
                    self.assertFalse(check(code=code), code)
                for body in (None, b"", b"link\n", b"link\nlink\nlink\n", b"link\nwarning\n"):
                    self.assertFalse(check(events=body))
                self.assertFalse(check(script=HERE / "smoke-test-relink.sh"))
                self.assertFalse(check(text + "extra trailing output\n"))
                self.assertFalse(check(text.replace("\n" + diagnostic + "\n", "\n")))
                self.assertFalse(check(text.replace("\n" + diagnostic + "\n", "\n" + diagnostic + "\n" + diagnostic + "\n")))
                # An extra count or changed binary/control earlier must not be hidden by the last check.
                for before, after in (("+ actual=17\n", "+ actual=29\n"),
                                      ("+ actual=2:37\n", "+ actual=2:17\n"),
                                      ("+ actual=29\n", "+ actual=29\n+ count=2\n"),
                                      ("+ check_links 29 2\n", "+ check_links 29 0\n"),
                                      ("/marked-declared-target/debug/second\n", "/marked-declared-target/debug/first\n"),
                                      ("/marked-declared-build\n", "/marked-other-build\n"),
                                      ("+ OHM_SMOKE_LINK_LOG=", "+ OTHER_LOG=")):
                    self.assertIn(before, text)
                    self.assertFalse(check(text.replace(before, after)), before)
                wrapped = re.sub(r"(?m)^\+ count=.*$", "+ count=20", text)
                self.assertNotEqual(wrapped, text)
                self.assertFalse(check(wrapped))


if __name__ == "__main__":
    unittest.main()
