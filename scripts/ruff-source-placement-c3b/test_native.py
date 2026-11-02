"""Exercise the actual source and binary record contracts before any Ruff visit."""

import json
import os
from pathlib import Path
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import footer
import scope


def main():
    study = json.loads((scope.HERE / "three-arm-protocol.json").read_bytes())
    for which, revision in [("C2", scope.C2), ("C3b", scope.C3)]:
        with scope.product(which) as reg:
            assert reg["roles"]["C"]["revision"] == revision
    phys = json.loads((scope.HERE / "physical-factory.json").read_bytes())
    a = phys["real_role_constructors"]
    assert (
        len(a["C"]["real_cpp"]["OhmSourcePlacement.cpp"]) == 1
        and not a["P"]["real_cpp"]["OhmSourcePlacement.cpp"]
    )
    assert (
        a["C"]["real_cpp"]["OhmSourcePlacement.cpp"][0]["sha256"]
        == "6d3e776e9582f1f27cea2fd8715562b6f9fdbcc13d660591c665171218f3c2c9"
    )
    seed = study["native"]["C2_native_reference"]
    assert (
        seed["total_CGUs"] == 125 and len(set(seed["forward"])) == 13 and seed["ordinary_writes"] == 8
    )

    def make(version, slot=17, extra=b""):
        wire = (
            b"OSP" + bytes([version]) + b"h" * 32 + b"CGU-GLOBAL-LINES\x01" + b"\0" * 9 + b"t" * 32
        )
        return (
            b"RSIC-index"
            + footer.MAGIC
            + struct.pack("<II", slot, len(wire))
            + wire
            + extra
            + footer.END
        )

    q = make(3)
    assert footer.parse(q)["entries"][0][0] == 17 and footer.parse(make(1), 1)
    assert footer.parse(b"RSICfoo" + footer.END) is None
    for b in (
        make(1),
        q[:-3],
        make(3, extra=b"xx"),
        q.replace(b"CGU-GLOBAL", b"CGU-MUTANT"),
        q.replace(b"OSP\x03", b"OSP\x01"),
    ):
        try:
            footer.parse(b)
            raise AssertionError("accepted corrupt physical input")
        except ValueError:
            pass
    print(
        "Both genuine source bindings, real guarded C++ construction, previous 13 physical placements, and five wire corruption negatives passed."
    )


if __name__ == "__main__":
    main()
