"""Verify the actual one-blob compiler build-script successor of the refused a9d85b2 source."""

from copy import deepcopy
from hashlib import sha1, sha256
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "ruff-source-placement-stock-writer"
sys.path.insert(0, str(ORIGINAL))
import stock_source as prev

need, git, oid = prev.need, prev.git, prev.oid
CPP, BRANCH = prev.CPP, prev.BRANCH
A9 = "a9d85b2241b2661d6b6615a0ed1aaf5ca7558b2b"
A9_TREE = "4b757e42a457031d7ed7fc32ddb2da1dbe06d783"
OLD_FACTORY = 41505848219
OLD_QA = "0509c465a456a4f10d7f422831cc4f4bfb57821e"
ORIGINAL_REG = "89fea90ea19bd791bdc94e8e35e112610fa9c55d"
BUILD = "compiler/rustc_llvm/build.rs"


def loaded(path):
    return json.loads(path.read_bytes())


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def descriptor(repo, rev, path):
    data = git(repo, "cat-file", "blob", rev + ":" + path)
    blob = oid(repo, rev + ":" + path)
    need(
        sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == blob
        and git(repo, "ls-tree", "-z", rev, "--", path)
        == ("100644 blob " + blob + "\t" + path + "\0").encode(),
        "incorrect original physical blob",
    )
    return data, {"blob": blob, "bytes": len(data), "sha256": sha256(data).hexdigest()}


def shape(repo, commit):
    need(
        re.fullmatch(r"[0-9a-f]{40}", commit)
        and git(repo, "rev-list", "--parents", "-n1", commit).decode().split() == [commit, A9]
        and oid(repo, A9 + "^{tree}") == A9_TREE
        and git(
            repo, "diff-tree", "-r", "--name-status", "--no-commit-id", "--no-renames", A9, commit
        )
        .decode()
        .splitlines()
        == ["M\t" + BUILD],
        "new source is not the one-file direct successor of the refused source",
    )
    original, reg = prev.binding(ORIGINAL)
    need(
        original["subject"] == A9 and reg["roles"]["C"]["revision"] == A9,
        "different original source factory",
    )
    before, p = descriptor(repo, A9, BUILD)
    after, c = descriptor(repo, commit, BUILD)
    needle = b"cxxflags.iter().any("
    need(
        before.count(needle) == 2
        and after
        in {
            before.replace(needle, s)
            for s in (b"cxxflags.into_iter().any(", b"(&cxxflags).into_iter().any(")
        }
        and p == original["physical_files"][BUILD]["selected"],
        "anything other than the original two iterator method calls changed",
    )
    measured = {}
    for path, record in original["physical_files"].items():
        _, actual = descriptor(repo, commit, path)
        need(
            actual == (c if path == BUILD else record["selected"]),
            "changed frozen LLVM, FFI or Rust code",
        )
        measured[path] = deepcopy(record)
        measured[path]["selected"] = actual
    need(
        measured[prev.CPP]["selected"]["sha256"] == prev.SELECTED,
        "different measured native BLAKE3 translation unit",
    )
    return {
        "schema": "actual-compiler-iterator-correction-1",
        "subject": commit,
        "tree": oid(repo, commit + "^{tree}"),
        "compiler": oid(repo, commit + ":compiler"),
        "parent": A9,
        "parent_tree": A9_TREE,
        "one_changed_file": BUILD,
        "before": p,
        "after": c,
        "physical_files": measured,
        "actual_duplicate_free_cohort": 41501796384,
    }


def bundle(raw, subject):
    header, split, body = raw.partition(b"\n\n")
    rows = header.splitlines()
    need(
        split
        and body.startswith(b"PACK")
        and 0 < len(raw) < 1 << 20
        and len(rows) == 3
        and rows[0] == b"# v2 git bundle"
        and rows[1].split(maxsplit=1)[0] == b"-" + A9.encode(),
        "wrong native source transport prerequisite",
    )
    rr = rows[2].decode().split()
    need(rr == [subject, "HEAD"], "wrong incoming source ref")
    return {
        "branch": rr[1],
        "prerequisite": A9,
        "sha256": sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def binding(directory=HERE):
    packet = loaded(directory / "source-packet.json")
    reg = loaded(directory / "registration.json")
    proto = loaded(directory / "protocol.json")
    raw = (directory / "candidate.bundle").read_bytes()
    need(
        reg["bundle"] == bundle(raw, packet["subject"])
        and packet["parent"] == A9
        and packet["parent_tree"] == A9_TREE
        and packet["one_changed_file"] == BUILD
        and packet["physical_files"][prev.CPP]["selected"]["sha256"] == prev.SELECTED
        and proto["source"] == reg["roles"]["C"]["revision"] == packet["subject"]
        and proto["complete_tree"] == reg["roles"]["C"]["tree"] == packet["tree"]
        and reg["roles"]["P"]["revision"] == prev.PARENT
        and reg["roles"]["C"]["compiler"] == packet["compiler"]
        and reg["changed_sources"][BUILD]["C"] == packet["after"]["blob"]
        and proto["source_packet_sha256"]
        == reg["source_packet_sha256"]
        == sha256((directory / "source-packet.json").read_bytes()).hexdigest(),
        "different actual source, transport, or independently prepared constructor registration",
    )
    return packet, reg


def freeze(repo, commit, source_bundle, digest):
    packet = shape(repo, commit)
    raw = source_bundle.read_bytes()
    transport = bundle(raw, commit)
    need(transport["sha256"] == digest, "bundle differs from independent complete transport")
    pbytes = encoded(packet)
    parent_p, original = prev.binding(ORIGINAL)
    reg = deepcopy(original)
    reg["previous_bundle_sha256"] = original["bundle"]["sha256"]
    reg["refused_explicit_bundle"] = original["bundle"]
    reg["bundle"] = transport
    reg["schema"] = "source-matched-genuine-iterator-repair"
    reg["roles"]["C"] = {"revision": commit, "tree": packet["tree"], "compiler": packet["compiler"]}
    reg["changed_sources"][BUILD]["C"] = packet["after"]["blob"]
    reg["source_packet_sha256"] = sha256(pbytes).hexdigest()
    proto = loaded(ORIGINAL / "protocol.json")
    proto["inherited_trees"][ORIGINAL.name] = oid(
        ORIGINAL, ORIGINAL_REG + ":scripts/" + ORIGINAL.name
    )
    proto.update(
        schema="source-matched-native-iterator-1",
        source=commit,
        complete_tree=packet["tree"],
        source_packet_sha256=reg["source_packet_sha256"],
        refused_source=A9,
        refused_factory=OLD_FACTORY,
        refused_qa=OLD_QA,
        refused_raw={
            "id": 13172450043,
            "bytes": 52900,
            "sha256": "1d3ccbbc256f6aa5af0d1258391e850b6a9fdb561c3b894f72a5633ec12f08f4",
        },
    )
    study = loaded(ORIGINAL / "selected-study.json")
    study["source"]["Stock4"] = commit
    study.pop("stock_factory")
    study.update(
        source_factory_protocol=sha256(encoded(proto)).hexdigest(),
        refused_source_registration=ORIGINAL_REG,
        native_factory_selection="One first-attempt successful source-bound factory receipt; fixed into physical-factory.json before any acquisition.",
    )
    study["excluded"].update(failed_factory=OLD_FACTORY, failed_source=A9, failed_product_count=0)
    data = {
        "candidate.bundle": raw,
        "source-packet.json": pbytes,
        "registration.json": encoded(reg),
        "protocol.json": encoded(proto),
        "selected-study.json": encoded(study),
    }
    need(all(not (HERE / n).exists() for n in data), "refusing to overwrite an enrolled source")
    for n, b in data.items():
        with (HERE / n).open("xb") as f:
            f.write(b)
    binding()


if __name__ == "__main__":
    freeze(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4])
