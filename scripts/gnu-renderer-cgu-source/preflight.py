"""Local proof for source reconstruction, native result recognition and the sealed transfer reader."""

import argparse
import gzip
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source import HERE, BASE, COMBINED, FORWARD, CALLABLE_TEST, FORWARD_TEST, need, reconstruct
from build import archive, manifest, sha, verdict, write
from restore import restore


def refuses(call, needle):
    try:
        call()
    except ValueError as error:
        need(needle in str(error), str(error))
        return str(error)
    raise AssertionError("receiver accepted mutation: " + needle)


def report(name, sig, good):
    return (
        "running 1 tests\ntest [run-make] tests/run-make/"
        + name
        + " ... "
        + ("ok" if good else "FAILED")
        + "\n"
        + sig
        + "\ntest result: "
        + ("ok. 1 passed; 0 failed;" if good else "FAILED. 0 passed; 1 failed;")
        + " 0 ignored; 0 measured; 551 filtered out; finished in 0.1s\n"
    )


def main(args):
    need(
        args.signed_objects.is_dir() and args.postsigned_objects.is_dir(),
        "missing Git source object dirs",
    )
    with tempfile.TemporaryDirectory(dir=args.scratch) as tmp:
        temp = Path(tmp)
        repo = temp / "isolated-git"
        subprocess.run(["git", "init", "-q", repo], check=True)
        os.environ["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = (
            str(args.signed_objects.resolve()) + ":" + str(args.postsigned_objects.resolve())
        )
        rows = reconstruct(repo, HERE / "packet", True)
        packet = temp / "mutant"
        shutil.copytree(HERE / "packet", packet)
        reg = json.loads((packet / "registration.json").read_text())
        head = reg["steps"][0]["head"]
        patch = packet / (head + ".patch.gz")
        old = patch.read_bytes()
        patch.write_bytes(old[:-1] + bytes([old[-1] ^ 1]))
        neg = [refuses(lambda: reconstruct(repo, packet, True), "corrupt packed patch")]
        patch.write_bytes(old)
        live = packet / "live-over-signed.pack"
        original_live = live.read_bytes()
        live.write_bytes(original_live[:-1] + bytes([original_live[-1] ^ 1]))
        neg.append(refuses(lambda: reconstruct(repo, packet, True), "corrupt live-base pack"))
        live.write_bytes(original_live)
        # Reseal a raw commit with a wrong tree to ensure verification continues inside the compressed transport.
        raw = reg["steps"][0]["tree"]
        reg["steps"][0]["tree"] = "0" * 40
        write(packet / "registration.json", reg)
        neg.append(refuses(lambda: reconstruct(repo, packet, True), "incorrect raw commit header"))
        reg["steps"][0]["tree"] = raw
        reg["roles"].pop("C")
        write(packet / "registration.json", reg)
        neg.append(refuses(lambda: reconstruct(repo, packet, True), "intentionally unenrolled"))
        f = args.derived_failure.read_text()
        need(
            "left: false" in f and "std::fmt::Debug" in f, "expected authentic parent runner diagnostic"
        )
        with gzip.open(args.callable_listing, "rt") as src:
            (owner,) = [
                s.split(" @@ ")[1].split("[")[0] for s in src if s.startswith("MONO_ITEM fn scoped @@")
            ]
        need(
            owner.startswith("fixture.") and "-callable.drop-" not in owner,
            "expected authentic old callable placement",
        )
        with gzip.open(args.callable_failure, "rt") as src:
            c = src.read()
        need(re.search(r"(?m)^fixture\.[0-9a-f]{16}\s*$", c), "missing actual callable run-make panic")
        known = {FORWARD_TEST: f, CALLABLE_TEST: c}
        for name, diagnostic in known.items():
            fail = report(name, diagnostic, False)
            good = report(name, "", True)
            verdict(fail, name, False, 1)
            verdict(good, name, True, 0)
            neg += [
                refuses(lambda: verdict(fail, name, False, 101), "missing named failing"),
                refuses(
                    lambda: verdict(good.replace(" ... ok", " ... ignored"), name, True, 0),
                    "missing named native",
                ),
                refuses(lambda: verdict(fail + "error[E0282]", name, False, 1), "fixture build"),
                refuses(lambda: verdict(good + good, name, True, 0), "one registered"),
            ]
        transfer = temp / "transfer"
        transfer.mkdir()
        donor = temp / "donor"
        donor.mkdir()
        native = donor / "driver"
        tool = donor / "rustc"
        native.write_bytes(b"P")
        tool.write_bytes(b"frontend")
        tool.chmod(0o755)
        m = manifest({Path("bin/rustc"): tool, Path("lib/driver"): native})
        archive({Path("bin/rustc"): tool, Path("lib/driver"): native}, transfer / "P-sdk.tar.zst")
        roles = {}
        for role, rev in [("P", BASE), ("F", FORWARD), ("C", COMBINED)]:
            native.write_bytes(role.encode())
            roles[role] = {
                "source": {"commit": rev},
                "driver": [sha(native), 1, native.stat().st_mode & 0o777],
            }
            if role != "P":
                subprocess.run(
                    ["zstd", "-q", "-o", transfer / ("driver-" + role + ".zst"), native], check=True
                )
        products = {p.name: [sha(p), p.stat().st_size] for p in transfer.iterdir()}
        fixture = {
            "qa": "test",
            "run": "7",
            "attempt": "1",
            "roles": roles,
            "products": products,
            "files": m,
            "driver": "lib/driver",
            "common_member_count": 1,
        }
        write(transfer / "manifest.json", fixture)
        for role in roles:
            dest = temp / role
            restore(transfer, dest, role, "test", 7, 1)
            need(
                (dest / "lib/driver").read_bytes() == role.encode()
                and (dest / "bin/rustc").read_bytes() == b"frontend",
                "wrong single-file role",
            )
        neg.append(
            refuses(
                lambda: restore(transfer, temp / "foreign", "P", "foreign", 7, 1), "different QA run"
            )
        )
        patch = transfer / "driver-C.zst"
        patch.write_bytes(patch.read_bytes()[:-1])
        neg.append(
            refuses(lambda: restore(transfer, temp / "broken", "P", "test", 7, 1), "transfer mismatch")
        )
        result = {
            "git_trees": rows,
            "negative_guards": neg,
            "source_parent_runner_stderr": sha(args.derived_failure),
            "callable_parent_listing": sha(args.callable_listing),
            "callable_rmake_stderr": sha(args.callable_failure),
            "callable_parent_owner": owner,
            "transfer_roundtrips": list(roles),
            "reporter": "synthetic pretty reports using real forwarder and callable rmake stderr, and signed callable MONO_ITEM",
            "actual_native_compilers_built": 0,
        }
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in (
        "signed-objects",
        "postsigned-objects",
        "derived-failure",
        "callable-listing",
        "callable-failure",
    ):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--scratch", type=Path)
    main(p.parse_args())
