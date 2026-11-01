"""Authenticate and reconstruct the measured compiler from the original E SDK and only changed regular files."""

import hashlib, json, os, shutil, stat, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from protocol import need


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def archive(folder, root, old, new, driver):
    folder.mkdir()
    diff = sorted(n for n in old if new[n] != old[n])
    need(
        set(old) == set(new) and len(old) == 81 and driver in diff and set(diff) <= {driver, "bin/rustdoc"},
        "unexpected source SDK delta",
    )
    result = {
        "format": 1,
        "parent": "393b4b05a4bfa3f531a36023846f86236a6b71a9",
        "candidate": "7c0c305743727cb08e3c1de61183c9cb953d3f33",
        "driver": driver,
        "members": {},
    }
    for i, n in enumerate(diff):
        f = root / n
        body = folder / (str(i) + ".zst")
        need(
            f.is_file()
            and f.resolve() == f
            and [sha(f), f.stat().st_size, stat.S_IMODE(f.stat().st_mode)] == new[n],
            ("wrong measured native member", n),
        )
        with body.open("xb") as out:
            subprocess.run(["zstd", "-q", "-1", "-T1", "-c", f], stdout=out, check=True)
        result["members"][n] = {"file": body.name, "media": sha(body), "parent": old[n], "candidate": new[n]}
    (folder / "manifest.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return verify(folder, old, new, driver)


def verify(folder, old, new, driver):
    obj = json.loads((folder / "manifest.json").read_bytes())
    diff = sorted(n for n in old if old[n] != new[n])
    need(
        obj["format"] == 1
        and obj["parent"] == "393b4b05a4bfa3f531a36023846f86236a6b71a9"
        and obj["candidate"] == "7c0c305743727cb08e3c1de61183c9cb953d3f33"
        and driver == obj["driver"]
        and len(old) == 81
        and set(old) == set(new)
        and driver in diff
        and set(obj["members"]) == set(diff) <= {driver, "bin/rustdoc"},
        "invalid original/overlay membership",
    )
    need(
        {f.name for f in folder.iterdir()} == {"manifest.json"} | {f"{i}.zst" for i in range(len(diff))},
        "unexpected overlay files",
    )
    for i, n in enumerate(diff):
        d = obj["members"][n]
        body = folder / (str(i) + ".zst")
        need(
            d["file"] == body.name
            and not body.is_symlink()
            and sha(body) == d["media"]
            and d["parent"] == old[n]
            and d["candidate"] == new[n],
            "wrong source or compressed member",
        )
        with subprocess.Popen(["zstd", "-qd", "-c", body], stdout=subprocess.PIPE) as p:
            h = hashlib.sha256()
            count = 0
            while data := p.stdout.read(2**20):
                h.update(data)
                count += len(data)
                need(count <= new[n][1], "overlay exceeds authenticated native size")
            need(
                p.wait() == 0 and [h.hexdigest(), count] == new[n][:2],
                "incorrect reconstructed native member",
            )
    return sha(folder / "manifest.json")


def restore(folder, logs, original, destination):
    records = {k: json.loads((logs / "sdk" / (k + ".json")).read_bytes()) for k in ("E", "R")}
    old, new = ({n: [x[0], x[4], x[3]] for n, x in records[k]["files"].items()} for k in ("E", "R"))
    verify(folder, old, new, records["R"]["driver"])
    manifest = json.loads((folder / "manifest.json").read_bytes())["members"]
    need(
        not destination.exists()
        and original.is_dir()
        and original.resolve() == original
        and set(str(p.relative_to(original)) for p in original.rglob("*") if not p.is_dir() or p.is_symlink())
        == set(old),
        "untrusted original or nonempty destination",
    )
    destination.mkdir()
    for n, row in old.items():
        f = original / n
        out = destination / n
        need(
            f.resolve() == f and [sha(f), f.stat().st_size, stat.S_IMODE(f.stat().st_mode)] == row,
            ("wrong parent native member", n),
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        if n in manifest:
            with out.open("xb") as dest:
                subprocess.run(["zstd", "-qd", "-c", folder / manifest[n]["file"]], stdout=dest, check=True)
            os.chmod(out, new[n][2])
        else:
            shutil.copy2(f, out)
        need(
            not out.samefile(f)
            and [sha(out), out.stat().st_size, stat.S_IMODE(out.stat().st_mode)] == new[n],
            ("wrong resulting file", n),
        )
    print(json.dumps({"reconstructed_members": len(new), "overlay_members": sorted(manifest)}))


if __name__ == "__main__":
    restore(*map(Path, sys.argv[1:]))
