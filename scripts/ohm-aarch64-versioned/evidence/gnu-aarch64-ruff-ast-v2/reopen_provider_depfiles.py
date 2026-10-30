"""Check a cross-build provider's actual Rust binary/rlib and depfile rules."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


MARKERS = {
    "hard": b"/dev/null/ohm-untracked-relink-inputs",
    "legacy": b"/dev/null/ohm-recheck-dependent-links",
    "versioned": b"/dev/null/ohm-recheck-dependent-links-v2",
}


def rules(body, filename, library, marker):
    """Match all code-bearing targets to the depfile's separately emitted ordinary inputs."""
    own_name = filename.encode()
    stem = own_name.removesuffix(b".d")
    assert stem + b".d" == own_name
    outputs = ({b"lib" + stem + b".rlib", b"lib" + stem + b".rmeta"} if library else {stem})
    dependencies = {}
    for line in body.splitlines():
        if not line.startswith(b"#") and b": " in line:
            target, inputs = line.split(b": ", 1)
            basename = target.rsplit(b"/", 1)[-1]
            assert basename not in dependencies
            dependencies[basename] = inputs.split()
    assert set(dependencies) == outputs | {own_name}
    ordinary = dependencies[own_name]
    assert ordinary and not any(item.startswith(b"/dev/null/ohm-") for item in ordinary)
    assert all(dependencies[target] == ordinary + [marker] for target in outputs)
    standalone = [line for line in body.splitlines() if line.startswith(b"/dev/null/ohm-")]
    assert standalone == [marker + b":"]


def verify(archive, expected_sha, source, marker):
    with archive.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == expected_sha
    with ZipFile(archive) as z:
        members = z.namelist()
        assert len(members) == len(set(members))
        terminal = json.loads(z.read("versioned-native-terminal.json"))
        assert terminal["compiler"] == source
        expected, observed, first = set(), {}, None
        for history, header in terminal["rosters"].items():
            raw = z.read(history + "/completed.json")
            assert hashlib.sha256(raw).hexdigest() == header["terminal"]
            finished = json.loads(raw)
            library = finished["placement"] == "library"
            assert finished["source"] == source and finished["placement"] in ("library", "direct")
            for case in finished["cases"]:
                if case["exit"] != 0 or case["name"].startswith("empty-"):
                    continue
                phase = history + "/" + case["name"]
                name = phase + "/actual-dep-info-provenance.json"
                expected.add(name)
                info = json.loads(z.read(name))
                assert info["crate"] == ("barrier" if library else "qa_owned_test")
                phase_hashes = []
                for key, file in info["files"].items():
                    if file["kind"] != "depfile":
                        continue
                    assert key == file["name"]
                    digest = file["sha256"]
                    body = z.read(phase + "/actual-files/" + digest)
                    assert len(body) == file["len"] and hashlib.sha256(body).hexdigest() == digest
                    filename = Path(key).name
                    rules(body, filename, library, marker)
                    phase_hashes.append(digest)
                    if first is None:
                        first = (body, filename, library)
                assert phase_hashes
                observed[phase] = sorted(phase_hashes)
        assert expected == {m for m in members if m.endswith("/actual-dep-info-provenance.json")}
    assert first is not None
    body, name, library = first
    for invalid in (body.replace(marker, b"/dev/null/ohm-wrong-marker", 1),
                    body.replace(marker + b":\n", b"", 1)):
        assert invalid != body
        try:
            rules(invalid, name, library, marker)
        except AssertionError:
            continue
        raise AssertionError("negative depfile control accepted")
    return {"artifact_sha256":expected_sha, "compiler":source, "mode":terminal["mode"],
            "marker":marker.decode(), "successful_retained_phases":len(expected),
            "checked_rustc_depfiles":sum(map(len,observed.values())), "distinct_payloads":len({m for rows in observed.values() for m in rows}),
            "raw_depfile_sha256_by_phase":observed, "negative_controls":2}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("provider_zip",type=Path)
    ap.add_argument("expected_artifact_sha256")
    ap.add_argument("expected_compiler_commit")
    ap.add_argument("marker",choices=MARKERS)
    ap.add_argument("--output",type=Path)
    args = ap.parse_args()
    result=verify(args.provider_zip,args.expected_artifact_sha256,args.expected_compiler_commit,MARKERS[args.marker])
    data=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if args.output:
        args.output.write_text(data)
    else:
        print(data,end="")


if __name__=="__main__":
    main()
