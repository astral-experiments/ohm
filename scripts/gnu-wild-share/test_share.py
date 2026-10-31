"""Offline unit controls. These counter values are generated fixtures, never observations."""

from copy import deepcopy
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kernel import COMMAND, SELECTORS, classify, snapshot
from verify import pair_results


def files(d):
    ids = {
        n: {"path": "/staged/" + n, "dev": 7, "ino": i + 1, "sha256": "0" * 64}
        for i, n in enumerate((*SELECTORS, "cargo", "proxy"))
    }
    size = 128
    (d / "abi.tsv").write_text("128\t0\t1\t3\t1\t1\t1\t1\t8\n")
    for n, bit in (("whole", 4096), ("subtree", 0)):
        (d / (n + "-attr.bin")).write_bytes(
            struct.pack("<IIQQQQQ", 0, size, 1, 0, 0, 3, 99 + bit).ljust(size, b"\0")
        )
    logfile = ["root\t1", "task\t1\t1\t0"]
    ex = []
    samples = ["0\t1\t0\t0\t24\t1500\t999\t999"]

    def ev(pid, n, args):
        p = ids[n]
        i = len(ex) + 1
        k = SELECTORS.index(n) + 1 if n in SELECTORS else 0
        ex.append(f"{i}\t{pid}\t{k}\t{int(n == 'wild')}\t7\t{p['ino']}\t{p['path']}")
        logfile.append(f"exec\t{pid}\t{i}")
        (d / f"args-{i:04d}").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
        if n == "wild":
            samples.append(f"{i}\t{pid}\t4\t0\t24\t{pid * 20}\t200\t200")

    def child(p, q):
        logfile.extend([f"spawn\t{p}\t{q}\t1", f"task\t{q}\t{q}\t{p}"])

    ev(1, "proxy", COMMAND)
    ev(1, "cargo", ["cargo", *COMMAND[2:]])
    out = {
        "ruff": "/staged/work/ruff",
        "integration_test": "/staged/work/integration_test-0123456789abcdef",
    }
    for i, (name, path) in enumerate(out.items()):
        p = 2 + i * 5
        child(1, p)
        ev(
            p,
            "rustc",
            [
                "rustc",
                "--crate-name",
                name,
                path + ".rlink",
                "-Z",
                "link-only",
                *(["--test"] if name == "integration_test" else []),
            ],
        )
        for j, n in enumerate(("cc", "collect2", "wild"), 1):
            child(p + j - 1, p + j)
            ev(
                p + j,
                n,
                [n, "-o", path, "-lgcc_s", "libzmij-a.rlib", "libserde_json-a.rlib"],
            )
        child(p + 3, p + 4)
    logfile.extend(f"exit\t{i}\t0\t0" for i in range(11, 0, -1))
    for name, rows in (
        ("tasks.tsv", logfile),
        ("exec.tsv", ex),
        ("samples.tsv", samples),
    ):
        (d / name).write_text("\n".join(rows) + "\n")
    return ids, out


class Tests(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.TemporaryDirectory()
        self.d = Path(self.store.name)
        self.ids, self.outputs = files(self.d)

    def tearDown(self):
        self.store.cleanup()

    def result(self):
        return classify(snapshot(self.d, "tree", self.ids), self.outputs, "ruff")

    def test_siblings(self):
        self.assertEqual(
            self.result(),
            {"whole": 1500, "outputs": {"ruff": 100, "integration_test": 200}},
        )

    def test_wrong_image(self):
        p = self.d / "exec.tsv"
        p.write_text(p.read_text().replace("4\t1\t7\t4", "4\t1\t7\t88", 1))
        with self.assertRaises(ValueError):
            self.result()

    def test_missing_sampling_child(self):
        p = self.d / "samples.tsv"
        p.write_text("\n".join(p.read_text().splitlines()[:-1]) + "\n")
        with self.assertRaises(ValueError):
            self.result()

    def test_nonfull_duty(self):
        p = self.d / "samples.tsv"
        p.write_text(p.read_text().replace("200\t200", "200\t199", 1))
        with self.assertRaises(ValueError):
            self.result()

    def test_overlap(self):
        p = self.d / "tasks.tsv"
        p.write_text(p.read_text().replace("spawn\t1\t7\t1", "spawn\t5\t7\t1"))
        with self.assertRaises(ValueError):
            self.result()

    def test_extra_compiler(self):
        p = self.d / "args-0003"
        p.write_bytes(p.read_bytes().replace(b"link-only", b"ordinary"))
        with self.assertRaises(ValueError):
            self.result()

    def test_omitted_linker_exit(self):
        p = self.d / "tasks.tsv"
        p.write_text(p.read_text().replace("exit\t5\t0\t0\n", ""))
        with self.assertRaises(ValueError):
            self.result()

    def test_wrong_destination(self):
        p = self.d / "args-0006"
        p.write_bytes(p.read_bytes().replace(b"/work/ruff", b"/work/nooo"))
        with self.assertRaises(ValueError):
            self.result()

    def test_denominator_and_one_failed_visit(self):
        pair = {"tree": self.result(), "plain": {"whole": 1520}}
        r = pair_results([pair] * 4)["pairs"][0]
        self.assertEqual(r["combined_observed_share"], 0.2)
        self.assertEqual(r["traced_zero_cost_ceiling"], 1.25)
        bad = deepcopy(pair)
        bad["plain"]["whole"] = 1800
        with self.assertRaises(ValueError):
            pair_results([pair, bad, pair, pair])

    def test_missing_pair(self):
        with self.assertRaises(ValueError):
            pair_results([])


if __name__ == "__main__":
    unittest.main()
