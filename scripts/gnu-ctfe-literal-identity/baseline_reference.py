"""Test the qualification reader on the preserved actual original 41-unit Ruff archive."""

from pathlib import Path
import gzip, json, os, subprocess, sys, tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ruff
from archive_fields import controls
from binding import need, save


def replay(root):
    slots = {}
    with tempfile.TemporaryDirectory() as w:
        tmp = Path(w)
        (tmp / "bodies").symlink_to((root / "bodies").resolve(strict=True))
        for label, original in (
            ("first-B", "first-B"),
            ("return-B", "return-B"),
            ("unchanged-B", "unchanged-B"),
            ("empty-B", "empty-build-B"),
        ):
            old = root / "Eoff" / original
            q = json.loads(gzip.decompress((old / "outcome.json.gz").read_bytes()))
            cur = tmp / "E" / label
            cur.mkdir(parents=True)
            (cur / "root.stdout.gz").symlink_to((old / "rmeta-list.stdout.gz").resolve(strict=True))
            m = q["source_target"]
            full = ruff.read_body(tmp / "bodies", m["rlib"]["sha256"])
            f = tmp / "baseline.rlib"
            f.write_bytes(full)
            archive = ruff.archive(f)
            f.unlink()
            need(
                archive["members"] == {a["name"]: a["sha256"] for a in m["members"]},
                "different physical member",
            )
            if label == "first-B":
                controls(full)
            slots["E", label] = dict(
                phase=label,
                rlib=m["rlib"]["sha256"],
                rmeta=m["rmeta"]["sha256"],
                listing=m["listing"],
                archive=archive,
                client=q["client"],
                macros=q["macros"],
            )
            f = tmp / "reader"
            f.write_bytes(ruff.read_body(tmp / "bodies", q["client"]["elf"]))
            f.chmod(0o700)
            need(
                [subprocess.check_output([f, n]).decode().strip() for n in ("pyi", "qno")]
                == q["client"]["runtime"]
                == ["56 Some(Stub)", "56 None"],
                "old real native ELF",
            )
        ruff.validate_repeat(slots["E", "return-B"], slots["E", "unchanged-B"])
        r = ruff.pair(slots["E", "first-B"], slots["E", "empty-B"], tmp, "E")
        need(
            r["changed_def_hashes"] == 10150 and r["matching_native_objects"] == 94,
            "baseline did not reproduce",
        )
        # Merely substituting the clean AST for the submitted warm artifact must never count as a reproduction.
        try:
            ruff.pair(slots["E", "empty-B"], slots["E", "empty-B"], tmp, "E")
        except (ValueError, AssertionError):
            pass
        else:
            raise ValueError("substituted baseline admitted")
        return r


if __name__ == "__main__":
    r = replay(Path(sys.argv[1]))
    if len(sys.argv) == 3:
        save(Path(sys.argv[2]), r)
    print(json.dumps(r, sort_keys=True))
