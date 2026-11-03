"""Exercise the actual index codec, KDF framing and named-file kernel lineage before hosted use."""

from hashlib import sha256
from pathlib import Path
import io
import json
import struct
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stock_scope as scope
import stock_footer
import migrate_index as migration


def rejects(call):
    try:
        call()
    except (ValueError, AssertionError, RuntimeError):
        return
    raise AssertionError("mutated input was admitted")


def run(tool):
    check = scope.base.need
    study = json.loads((HERE / "selected-study.json").read_bytes())
    scope.schedule(study)
    check(
        study["source_factory_protocol"] == scope.base.sha(HERE / "protocol.json"),
        "wrong source packet",
    )
    wrong = dict(study, blocks=list(reversed(study["blocks"])))
    rejects(lambda: scope.schedule(wrong))
    prior = b"RSIC\0frozen-genuine-format-control"
    obj = Path("/bin/true").read_bytes()
    with patch.object(migration, "B3SUM", tool):

        def pack(version, filename, slot, changed=False):
            wire = (
                b"OSP"
                + bytes([version])
                + sha256(bytes([version]) + filename).digest()
                + b"CGU-GLOBAL-LINES\x01"
                + (b"other" if changed else b"lines")
            )
            sealed = wire + migration.framed_seal(filename, wire)
            return struct.pack("<II", slot, len(sealed)) + sealed

        def table(ver, changed=False):
            return (
                prior
                + stock_footer.MAGIC
                + pack(ver, b"other object", 1)
                + pack(ver, obj, 4, changed)
                + stock_footer.END
            )

        for old, new in ((3, 4), (4, 3)):
            own, other = table(new), table(old)
            changed, proof = migration.swap(own, new, obj, other, old, 4)
            check(
                proof["destination_slot"] == 4
                and proof["unchanged_records"] == 1
                and changed[: proof["offset"]] == own[: proof["offset"]]
                and changed != own
                and changed != other,
                "incorrect exchange",
            )
            rejects(lambda: migration.swap(own, new, obj + b"x", other, old, 4))
            rejects(lambda: migration.swap(own, new, obj, other, new, 4))
            rejects(lambda: migration.swap(own, new, obj, table(old, True), old, 4))
            rejects(lambda: migration.swap(own, new, obj, other[:-1], old, 4))
            rejects(lambda: migration.swap(own, new, obj, other, old, 1))
            wrong = bytearray(other)
            wrong[-len(stock_footer.END) - 1] ^= 1
            rejects(lambda: migration.swap(own, new, obj, bytes(wrong), old, 4))
            rejects(lambda: stock_footer.parse(changed, new))
        orig = "/sessions/old/work-products.bin"
        dest = "/sessions/new/work-products.bin"
        links = f'link("{orig}", "{dest}") = 0\n'.encode()
        reads = f'openat(AT_FDCWD, "{dest}", O_RDONLY|O_CLOEXEC) = 8<{dest}>\n'.encode()
        path = migration.kernel_read(
            [("exec.100", io.BytesIO(links)), ("exec.101", io.BytesIO(reads))], orig
        )
        check(
            len(path) == 2 and path[0]["line_sha256"] == sha256(links).hexdigest(),
            "missing prior-file lineage",
        )
        rejects(lambda: migration.kernel_read([("exec.101", io.BytesIO(reads))], orig))
        rejects(
            lambda: migration.kernel_read(
                [("exec.100", io.BytesIO(links + reads.replace(b"O_RDONLY", b"O_WRONLY")))], orig
            )
        )
        rejects(
            lambda: migration.kernel_read(
                [("exec.100", io.BytesIO(links.replace(b" = 0", b" = -1 EEXIST") + reads))], orig
            )
        )
    print(
        "Both authentic-seal shapes, 14 corruption/format refusals, named-file chain and schedule controls passed."
    )


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) == 2 else "/usr/bin/b3sum")
