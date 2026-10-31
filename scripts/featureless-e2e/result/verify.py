"""Replay the frozen two-worker reader from its exact inputs, or cross-check both original Actions ZIPs."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
PACK = "bfdc81b7f127ceafecbd975eeaf4a979458f832fd041922dd9bf8797b278bfc0"
VERDICT = "7e2bc4c6d0b1cf22f8133322701dda35d1750a790e95b59cd480003be06534e7"
RUN = 41163189762
HEAD = "69c21b3ecf8510871c346f751c60866e302708d5"


def h(b):
    return hashlib.sha256(b).hexdigest()


def main(args):
    assert bool(args.strict_zip) == bool(args.pr293_zip)
    source = HERE / "source.zst"
    assert source.stat().st_size == 341253 and h(source.read_bytes()) == PACK
    with subprocess.Popen(["zstd", "-dq", "-c", source], stdout=subprocess.PIPE) as p:
        contents = {}
        with tarfile.open(fileobj=p.stdout, mode="r|") as t:
            for entry in t:
                assert entry.isfile() and 0 <= entry.size <= 24 * 2**20 and entry.name not in contents
                b = t.extractfile(entry).read()
                assert len(b) == entry.size and (entry.name == "index.json" or h(b) == entry.name)
                contents[entry.name] = b
        assert not any(p.stdout.read()) and p.wait() == 0
    index = json.loads(contents.pop("index.json"))
    assert (index["schema"], index["run"], index["attempt"], index["head"], index["verdict_sha256"]) == (
        1, RUN, 1, HEAD, VERDICT)
    assert len(contents) == 203 and len(index["members"]) == 536
    assert set(contents) == {v[3] for v in index["members"].values()}
    assert index["inputs"]["strict"][0] == 13027159509 and index["inputs"]["293"][0] == 13027883805
    exact = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for role, archive in (("strict", args.strict_zip), ("293", args.pr293_zip)):
            metadata = index["inputs"][role]
            z = None
            if archive:
                with archive.open("rb") as f:
                    assert archive.stat().st_size == metadata[2] and hashlib.file_digest(f, "sha256").hexdigest() == metadata[3]
                z = zipfile.ZipFile(archive)
                assert len([x for x in z.infolist() if not x.is_dir()]) == metadata[4] and z.testzip() is None
            try:
                for name,(raw_size,raw_hash,size,sha) in index["members"].items():
                    if not name.startswith(role+"/"):
                        continue
                    relative = Path(name)
                    assert not relative.is_absolute() and ".." not in relative.parts
                    content = contents[sha]
                    assert len(content) == size
                    if z:
                        raw = z.read(str(relative.relative_to(role)))
                        assert len(raw) == raw_size and h(raw) == raw_hash
                        assert (gzip.decompress(raw) if name.endswith(".gz") else raw) == content
                    elif name.endswith(".gz"):
                        # The source ZIP used the Unix OS byte. Python releases disagree on its default.
                        raw = gzip.compress(content, compresslevel=1, mtime=0)
                        raw = raw[:9] + bytes([3]) + raw[10:]
                        assert gzip.decompress(raw) == content
                    else:
                        raw = content
                        assert len(raw) == raw_size and h(raw) == raw_hash
                    exact += int(len(raw) == raw_size and h(raw) == raw_hash)
                    dest = root / relative
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_bytes(raw)
            finally:
                if z:
                    z.close()
        output = root / "result.json"
        subprocess.run([sys.executable, "-IB", HERE.parent / "reopen.py", root / "strict", root / "293",
                        "--head", HEAD, "--run", str(RUN), "--output", output], check=True)
        raw = output.read_bytes()
        assert h(raw) == VERDICT
        if args.output:
            args.output.write_bytes(raw)
    print(f"536/536 original decompressed inputs. {exact}/536 exact ZIP member encodings. Result {VERDICT}.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--strict-zip",type=Path)
    p.add_argument("--pr293-zip",type=Path)
    p.add_argument("--output",type=Path)
    main(p.parse_args())
