"""Recount the durable observations, optionally fetching every complete original native program."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from paired_counts import paired_stats, verify


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Retained:
    """Serve the original logical streams stored uncompressed inside the zstd bundle."""

    def __init__(self, path, checksum):
        assert digest(path.read_bytes()) == checksum
        body = subprocess.check_output(["zstd", "-qdc", path])
        with tarfile.open(fileobj=io.BytesIO(body)) as archive:
            self.files = {e.name: archive.extractfile(e).read() for e in archive}
        digests = json.loads(self.files["original-members.json"])
        assert set(digests) == self.files.keys() - {"original-members.json", "native-archive-readback.json"}
        for name, (original, uncompressed) in digests.items():
            assert digest(self.files[name]) == uncompressed
            if not name.endswith(".raw"):
                assert original == uncompressed

    def read(self, name):
        if name.endswith(".gz"):
            return gzip.compress(self.files[name[:-3] + ".raw"], compresslevel=2, mtime=0)
        return self.files[name]


def complete(item, order, scratch):
    gh = os.environ.get("GH_BIN") or shutil.which("gh-auto") or shutil.which("gh")
    if not gh:
        raise RuntimeError("Set GH_BIN to the GitHub CLI used to access the original run.")
    endpoint = "repos/astral-experiments/ohm/actions/artifacts/" + str(item["archive"])
    meta = json.loads(subprocess.check_output([gh, "api", endpoint]))
    assert not meta["expired"] and meta["digest"] == "sha256:" + item["zip_sha256"]
    assert (meta["workflow_run"]["id"], meta["workflow_run"]["head_sha"]) == (41104410375, "61127b2e9531769dea162b31a267d86a0368b479")
    scratch.seek(0)
    scratch.truncate(0)
    subprocess.run([gh, "api", endpoint + "/zip"], stdout=scratch, check=True)
    assert scratch.tell() == item["zip_bytes"]
    scratch.seek(0)
    assert hashlib.file_digest(scratch, "sha256").hexdigest() == item["zip_sha256"]
    scratch.seek(0)
    with zipfile.ZipFile(scratch) as z:
        return verify(z, order, True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--complete-archives", action="store_true",
                        help="download the original Actions ZIPs and reopen all 72 Linux AArch64 ELF files")
    args = parser.parse_args()
    registration = json.loads((HERE / "registration.json").read_bytes())
    plan = json.loads((HERE / "registered-pairs.json").read_bytes())
    orders = plan["schedules"]["holdout"]
    assert len(orders) == 12 and orders.count("PC") == orders.count("CP") == 6
    assert [item["position"] for item in registration["pairs"]] == list(range(1, 13))
    observations = []
    with tempfile.TemporaryFile() as scratch:
        for item, order in zip(registration["pairs"], orders):
            compact = Retained(HERE / "pairs" / f'{item["position"]:02}.tar.zst', item["retained_sha256"])
            original = json.loads(compact.read("native-archive-readback.json"))
            assert (original["artifact"], original["sha256"], original["size"]) == (item["archive"], item["zip_sha256"], item["zip_bytes"])
            assert original["run"] == registration["run"] == 41104410375 and original["head"] == registration["workflow"]
            verified = verify(compact, order, True, original_images=False)
            assert verified["physical_ELFs"] == 0 and original["pair"]["physical_ELFs"] == 6
            same = json.loads(json.dumps(verified))
            same.pop("physical_ELFs")
            assert same == {k: v for k, v in original["pair"].items() if k != "physical_ELFs"}
            if args.complete_archives:
                assert json.loads(json.dumps(complete(item, order, scratch))) == original["pair"]
            observations.append(verified)
    results = paired_stats(observations, orders)
    assert results == json.loads((HERE / "results.json").read_bytes())
    for phase, metrics in results.items():
        for metric, row in metrics.items():
            print(phase, metric, row["n"], "pairs; median", round(row["median"], 4),
                  "interval", row.get("median_interval_96_14"), "sharp 2x p", row.get("sharp_2x_p"))
    if args.complete_archives:
        print("Reopened all 72 original AArch64 native ELF files and their executable text.")
    else:
        print("Recounted original clocks, unit rosters, physical storage, clean-build and native program records.")


if __name__ == "__main__":
    main()
