"""Reopen the five native workers, the two original workflow rulings, and every controlled rmeta comparison."""

import argparse
import fnmatch
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))
import project
import reopen

SUBJECT = "51e3f8d6216dff5ac5ed894909711e28899e2860da8c043286670d5c01acde63"
HASHES = {
    "projection": SUBJECT,
    "original-member-index": "6ba4ba6b495ec02956d61b16e24f824b47c1935c1199e8d29bf6783b995e50ac",
    "migration-metadata-headers": "776da0e1aa7aa14df490895fd4bf978f6bc47b97a34895f54763160b040b24f3",
    "official-readback": "469758ccc485bc27feae70021cdaa29346cc4b4f608a8a6c057058748aef8162",
}


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(name):
    raw = gzip.decompress((HERE / (name + ".json.gz")).read_bytes())
    project.need(digest(raw) == HASHES[name], "modified " + name)
    return json.loads(raw)


class Member:
    def __init__(self, archive, path=""):
        self.archive = archive
        self.path = PurePosixPath(path)

    def __truediv__(self, name):
        return Member(self.archive, self.path / name)

    def __str__(self):
        return str(self.path)

    def __lt__(self, rhs):
        return str(self) < str(rhs)

    @property
    def name(self):
        return self.path.name

    @property
    def parent(self):
        return Member(self.archive, self.path.parent)

    def open(self, mode="rb"):
        project.need(mode == "rb", "read-only archive")
        return self.archive.open(str(self))

    def read_bytes(self):
        return self.archive.read(str(self))

    def is_file(self):
        return str(self) in self.archive.NameToInfo and not self.archive.getinfo(str(self)).is_dir()

    def glob(self, pattern):
        prefix = str(self.path) + "/"
        return [
            Member(self.archive, n)
            for n in self.archive.namelist()
            if n.startswith(prefix)
            and fnmatch.fnmatchcase(n[len(prefix) :], pattern)
            and len(n[len(prefix) :].split("/")) == len(pattern.split("/"))
        ]


def verify(originals):
    need = project.need
    subjects = json.loads((HERE / "originals.json").read_text())
    all_members = load("original-member-index")
    runs = load("official-readback")
    data = load("projection")
    headers = {h: bytes.fromhex(b) for h, b in load("migration-metadata-headers").items()}
    need(
        set(subjects) == set(all_members) and len(subjects) == 7 and len(headers) == 520, "missing originals"
    )
    need(
        runs[str(project.RUN)]["success"] is False and len(runs[str(project.RUN)]["issues"]) == 42,
        "missing failed metadata gate",
    )
    need(
        runs[str(project.TEST_RUN)]["success"] is True and not runs[str(project.TEST_RUN)]["issues"],
        "e2e result changed",
    )
    for name, rec in sorted(subjects.items()):
        members = all_members[name]
        need(
            digest(canonical(members)) == rec["membership_sha256"] and len(members) == rec["members"],
            "wrong file index",
        )
        if originals is not None:
            archive = originals / (name + ".original.zip")
            with archive.open("rb") as f:
                need(
                    hashlib.file_digest(f, "sha256").hexdigest() == rec["zip_sha256"]
                    and archive.stat().st_size == rec["zip_bytes"],
                    "wrong original " + name,
                )
            with zipfile.ZipFile(archive) as z:
                raw = {v.filename: [v.file_size, digest(z.read(v))] for v in z.infolist() if not v.is_dir()}
                need(raw == members, "different original observation " + name)
                official = runs[str(rec["run"])]
                if rec["role"] == "independent-readback":
                    need(
                        len(raw) == 1 and json.loads(z.read(next(iter(raw)))) == official,
                        "different workflow ruling",
                    )
                else:
                    reread = reopen.one(Member(z), rec["role"], rec["run"], rec["head"])
                    need(
                        reread == official["roles"][rec["role"]],
                        "original independent verifier disagreed " + name,
                    )
        if rec["role"] == "independent-readback":
            continue
        role = rec["role"]
        result = data[role]
        official = runs[str(rec["run"])]["roles"][role]
        need(
            result["issues"] == official["issues"] and set(result["visits"]) == set(official["visits"]),
            "phase accounting changed",
        )
        if originals is not None:
            need(
                json.loads(canonical(project.work(originals, role))) == result,
                "per-unit reconstruction differs " + role,
            )
        for phase, visit in result["visits"].items():
            want_bad = phase.endswith("/invalid")
            need(
                visit["status"] == (101 if want_bad else 0)
                and visit["terminal"] == {"reason": "build-finished", "success": not want_bad},
                "unexpected normal Cargo verdict",
            )
            if want_bad:
                need(
                    {e["code"] for e in visit["errors"]} == {"E0308"}
                    and all(
                        any("OHM_ACTUAL_COMPILER_MIGRATION_E0308" in s for s in span[3])
                        for e in visit["errors"]
                        for span in e["primary"]
                    ),
                    "wrong malformed input",
                )
            else:
                need(
                    not visit["errors"] and not visit["rmeta"]["wrong_issuer"],
                    "valid command received wrong crate metadata",
                )
            st = result["state"][phase]
            need(
                st["allocated"] == official["visits"][phase]["allocated"]
                and sum(st["by_root_allocated"].values()) - st["cross_root_allocated"] == st["allocated"],
                "cross-root storage mismatch",
            )
            if phase.startswith("trace/"):
                need(
                    sum(visit["physical"].values())
                    == visit["physical_compiler_count"]
                    == len(visit["compiler_argv_census"]),
                    "missing actual compiler",
                )
        if role.startswith("e2e-"):
            tests = result["test"]
            for phase, t in tests.items():
                is_reversed = phase.endswith(("/edited", "/edit-repeat", "/reversed"))
                clean = tests["clean/reversed" if is_reversed else "clean/original"]
                need(
                    t == clean and t["count"] == len(set(t["names"])) == (199 if is_reversed else 200),
                    "different actual test binary/list",
                )
                need(
                    ("notebook::cells_after_cell_magic" in t["names"]) != is_reversed, "wrong genuine example"
                )
            for phase in ("trace/edited", "trace/restored"):
                need(result["visits"][phase]["returned_e2e_links"] == 1, "missing output link")
            continue
        need(
            len(result["issues"]) == 14
            and all(s.endswith("workspace metadata bytes differ from empty") for s in result["issues"]),
            "clean-copy mismatch lost",
        )
        for phase, values in result["unit_values"].items():
            for value in values:
                if not value or not value["size"]:
                    continue
                h = value["sha256"]
                b = headers[h]
                need(
                    digest(b) == members["rmeta-headers/" + h + ".bin"][1]
                    and project.issuer(b) == value["stamp"],
                    "different actual metadata envelope",
                )
        for label, cp in result["comparisons"].items():
            left, right = label.split(" vs ")
            a, b = (result["unit_values"][n] for n in (left, right))
            diff = {}
            lost = []
            added = []
            sz = 0
            stamp = 0
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                if not x or not y:
                    if x and not y:
                        lost.append(i)
                    if y and not x:
                        added.append(i)
                elif x != y:
                    sz += x["size"] != y["size"]
                    stamp += x["stamp"] != y["stamp"]
                    diff[str(i)] = (
                        project.first_header(headers[x["sha256"]], headers[y["sha256"]])
                        if x["size"] and y["size"]
                        else {"empty": True}
                    )
            need(
                diff == cp["different_units"]
                and sz == cp["changed_sizes"]
                and stamp == cp["changed_issuer"]
                and lost == cp["keys_lost"]
                and added == cp["keys_added"],
                "per-unit rmeta contrast violated",
            )
        c = result["comparisons"]["pmu/cold vs trace/cold"]
        need(
            c["same_source_bytes"]
            and (c["changed_hashes"], c["changed_sizes"], c["changed_issuer"]) == (24, 0, 0),
            "missing pristine baseline control",
        )
        c = result["comparisons"]["pmu/upgrade-first vs pmu/upgrade-second"]
        need(c["changed_hashes"] == 0 and not c["keys_lost"] and not c["keys_added"], "first repeat differs")
        for stream in ("pmu", "trace"):
            w = result["install"][stream + "-comparison"]
            need(
                w["same_ino"] == 0
                and w["same_mtime"] == 0
                and (w["same_rustc_vv"] == (role != "signed-to-candidate")),
                "failed install/sham",
            )
            if role == "stage-to-sham":
                need(w["overlapping_regulars"] == w["same_digest"] == 66, "changed sham contents")
        v = result["visits"]["trace/upgrade-first"]
        need(
            v["physical_compiler_count"] == 304 and v["returned_artifact_count"] == 303 and v["wild"] == 48,
            "wrong replacement population",
        )
    for phase in data["e2e-parent"]["test"]:
        need(
            data["e2e-parent"]["test"][phase] == data["e2e-candidate"]["test"][phase],
            "compiler arms returned different test programs",
        )
    print(
        "Seven custody records; 100 actual Cargo visits: 28 e2e pass, 72 migration visits with 42 original rmeta comparison failures."
    )
    print("Per-unit JSON SHA-256", SUBJECT)
    if originals is not None:
        print("All seven original ZIPs and every enclosed member independently reopened.")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--originals", type=Path, help="Directory containing the seven SHA-256-registered .original.zip files"
    )
    verify(cli.parse_args().originals)
