"""Retain each Cargo-reported external compiler input by content, outside the counter."""
import hashlib
from pathlib import Path
import subprocess

seen = {}


def path_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def capture(rows, members):
    inventory = []
    for row in rows:
        package = row["package_id"]
        if not package.startswith(("registry+", "git+")):
            continue
        for filename in row["filenames"]:
            path = Path(filename)
            st = path.stat()
            state = (str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            key = seen.get(state)
            if key is None:
                key = path_sha(path)
                body = members / (key + ".external.zst")
                if not body.exists():
                    subprocess.run(["zstd", "-q", "-2", "-T1", path, "-o", body], check=True)
                end = path.stat()
                assert (end.st_dev, end.st_ino, end.st_size, end.st_mtime_ns, end.st_ctime_ns) == state[1:]
                seen[state] = key
            inventory.append([package, row["target"]["name"], row["target"]["kind"], str(path), st.st_size, key])
    assert inventory and len({tuple((row[0], row[1], row[3])) for row in inventory}) == len(inventory)
    return sorted(inventory)


def verify(records, rows, members, verified):
    expected = sorted([r["package_id"], r["target"]["name"], r["target"]["kind"], s]
                      for r in rows if r["package_id"].startswith(("registry+", "git+")) for s in r["filenames"])
    assert expected and sorted(r[:4] for r in records) == expected
    for _, _, _, _, size, sha in records:
        if sha in verified:
            assert size == verified[sha]
            continue
        with subprocess.Popen(["zstd", "-dq", "-c", members / (sha + ".external.zst")], stdout=subprocess.PIPE) as process:
            digest = hashlib.sha256()
            total = 0
            while chunk := process.stdout.read(1 << 20):
                digest.update(chunk)
                total += len(chunk)
            assert process.wait() == 0 and total == size and digest.hexdigest() == sha, ("different external product", sha)
        verified[sha] = size
    return records
