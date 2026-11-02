"""Reopen the positive source case and require rejection of independent substitutions."""

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fix_source as f

HEAD = "fba2663650927209e3589fdc807194f66271bd5a"
TREE = "2dcf7a694435c94e78994fedfde224964d9d8c40"
BUNDLE = "c1bbcf0c286d33fea15504a90458d5b36d75566aef8f89f25f5d34d1ff67981a"
PATCHED = "ac73ece6038d1f63f44814457e5420f2df5a4e2e50c78c2b13541f166c683f85"


def main():
    p, reg = f.binding()
    f.need(
        (p["subject"], p["tree"], p["after"]["sha256"]) == (HEAD, TREE, PATCHED)
        and reg["bundle"]["sha256"] == BUNDLE
        and reg["roles"]["C"]["compiler"] == p["compiler"],
        "different reviewed build source",
    )
    old, _ = f.prev.binding(f.ORIGINAL)
    f.need(
        all(k == f.BUILD or v == old["physical_files"][k] for k, v in p["physical_files"].items())
        and set(p["physical_files"]) == set(old["physical_files"]),
        "unreviewed C++ or Rust change",
    )
    tc = f.loaded(HERE / "repair-proof/typecheck.json")
    f.need(
        tc["previous_source"] == p["before"]["sha256"]
        and tc["new_source"] == PATCHED
        and tc["processes"]["previous"]["exit"] != 0
        and tc["processes"]["fixed"]["exit"] == 0
        and (HERE / "repair-proof/previous.stderr").read_bytes().count(b"error[E0599]") == 2
        and (HERE / "repair-proof/fixed.stderr").read_bytes() == b"",
        "incorrect original complete local build-script typechecks",
    )
    names = ("source-packet.json", "registration.json", "protocol.json", "candidate.bundle")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for ix in range(6):
            for n in names:
                shutil.copyfile(HERE / n, root / n)
            if ix < 3:
                raw = (root / names[3]).read_bytes()
                if ix == 0:
                    raw = raw.replace(HEAD.encode(), b"0" * 40, 1)
                elif ix == 1:
                    raw = raw.replace(f.A9.encode(), b"1" * 40, 1)
                else:
                    raw = raw[:-1] + bytes([raw[-1] ^ 1])
                (root / names[3]).write_bytes(raw)
            else:
                n = names[ix - 3]
                row = f.loaded(root / n)
                if ix == 3:
                    row["physical_files"][f.CPP]["selected"]["sha256"] = "0" * 64
                elif ix == 4:
                    row["roles"]["C"]["revision"] = f.A9
                else:
                    row["source_packet_sha256"] = "3" * 64
                (root / n).write_bytes(f.encoded(row))
            try:
                f.binding(root)
            except (ValueError, KeyError):
                continue
            raise ValueError("substituted source unexpectedly accepted " + str(ix))
    print(
        "Authenticated complete historical source, independently typechecked two-call correction, and 6 refused substitutions."
    )


if __name__ == "__main__":
    main()
