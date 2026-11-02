"""Verify the selected source binding and reject incorrect physical transports."""

import gzip
import json
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stock_source as src


def rejects(call):
    try:
        call()
    except (ValueError, AssertionError):
        return
    raise AssertionError("wrong source was accepted")


def main():
    packet, reg = src.binding(HERE)
    data = (HERE / "candidate.bundle").read_bytes()
    subject = packet["subject"]
    assert subject == "a9d85b2241b2661d6b6615a0ed1aaf5ca7558b2b"
    assert packet["tree"] == "4b757e42a457031d7ed7fc32ddb2da1dbe06d783"
    assert src.sha256(gzip.decompress((HERE / "reviewed.patch.gz").read_bytes())).hexdigest() == src.PATCH
    assert src.bundle_header(data, subject) == reg["bundle"]
    assert (
        src.git(HERE, "bundle", "list-heads", HERE / "candidate.bundle").decode().strip()
        == subject + " " + reg["bundle"]["branch"]
    )
    rejects(
        lambda: src.bundle_header(data.replace(src.GUARDED.encode(), subject.encode(), 1), subject)
    )
    rejects(lambda: src.bundle_header(data, src.GUARDED))
    rejects(
        lambda: src.bundle_header(
            data.replace(b"\n\nPACK", b"\n" + subject.encode() + b" HEAD\n\nPACK", 1), subject
        )
    )
    rejects(lambda: src.bundle_header(data[:-1].replace(b"\n\nPACK", b"\n\nBAD!", 1), subject))
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name in (
            "root-source-attestation.json",
            "source-packet.json",
            "registration.json",
            "protocol.json",
        ):
            (d / name).write_bytes((HERE / name).read_bytes())
        altered = json.loads((d / "source-packet.json").read_bytes())
        del altered["reviewed_sha256"][src.CPP]
        (d / "source-packet.json").write_text(json.dumps(altered))
        rejects(lambda: src.binding(d))
        (d / "source-packet.json").write_bytes((HERE / "source-packet.json").read_bytes())
        (d / "root-source-attestation.json").write_bytes(b"{}\n")
        rejects(lambda: src.binding(d))
    print(
        "Whole source registration, actual original Git bundle and six wrong-source/transport controls passed."
    )


if __name__ == "__main__":
    main()
