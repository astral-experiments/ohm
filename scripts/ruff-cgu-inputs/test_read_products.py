import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from green_probe import coverage
from read_products import recorded_products


def string(text):
    return bytes([len(text)]) + text + b"\xc1"


VERSION = b"1.99.0-dev (008a21ac0 2026-11-01) (ohm-1.99.0-22)"
HEADER = b"RSIC\x0a\x00" + bytes([len(VERSION)]) + VERSION
KEY = struct.pack("<QQ", 123, 456)
RECORD = KEY + string(b"example") + b"\x01" + string(b"o") + string(b"example.o")
TAIL = b"rust-end-file"


class WorkProducts(unittest.TestCase):
    def test_missing_and_physical_product(self):
        raw = HEADER + b"\x01" + RECORD + TAIL
        files = {"example.o": {"sha256": "actual receipt"}}
        row = recorded_products(raw, files)[KEY.hex()]
        self.assertEqual(row["words"], (123, 456))
        self.assertEqual(row["cgu"], "example")
        self.assertTrue(row["all_present"])
        self.assertEqual(row["saved"]["o"]["physical"], files["example.o"])
        self.assertFalse(recorded_products(raw, {})[KEY.hex()]["all_present"])

    def test_signed_cgu_and_qualified_native_identity(self):
        cgu = "app6md24z3cxw0zevcj31kxdh"
        native = "ruff_workspace.74f136ef346eb9fb." + cgu
        row = dict(cgu=cgu, actual_cgu_reuse="No", reason="already-red")
        self.assertEqual(
            coverage([native], [native], [row]),
            dict(rejected=1, independently_identical_causes={"already-red": 1}),
        )
        for args in (
            ([native], [], []),
            ([native, native.replace("74f1", "84f1")], [], [row]),
            ([native], ["other"], [row]),
            ([native], [], [row, row]),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                coverage(*args)

    def test_malformed_or_wrong_release(self):
        one = b"\x01" + RECORD
        for raw in (
            HEADER + b"\x02" + RECORD * 2 + TAIL,
            HEADER + one + b"unused" + TAIL,
            HEADER.replace(b"22)", b"23)") + one + TAIL,
            HEADER + b"\x81\x00" + RECORD + TAIL,
            HEADER + one.replace(b"example.o", b"../file.o") + TAIL,
            HEADER + one[:-2] + TAIL,
            HEADER + one[:-1] + b"\x00" + TAIL,
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                recorded_products(raw, {})


if __name__ == "__main__":
    unittest.main()
