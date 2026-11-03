"""Reopen both genuine source-built SDKs; the C3b path uses its immutable original receiver."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_scope as scope
from stock_scope import base as shared

CRATES, need, sha, save, capsule = (
    shared.CRATES,
    shared.need,
    shared.sha,
    shared.save,
    shared.capsule,
)
FACTORY, FACTORY_QA = scope.STOCK_FACTORY, scope.STOCK_QA


def install(root, reg):
    recorded = json.loads((scope.HERE / "physical-factory.json").read_bytes())
    need(
        recorded["factory"] == FACTORY
        and recorded["qa"] == FACTORY_QA
        and recorded["source"] == reg["roles"]["C"]["revision"],
        "wrong closed genuine constructor",
    )
    root.mkdir()
    outer = root / "actual-factory.zip"
    # The established archive reader verifies the real branch, commit, terminal, size and digest.
    receiver = scope.receiver
    prior = receiver.BRANCH
    try:
        receiver.BRANCH = scope.BRANCH
        row = receiver.archive(
            FACTORY, FACTORY_QA, "placement-stock-fix-matched-stage", outer, 769 << 20
        )
    finally:
        receiver.BRANCH = prior
    need(row == recorded["archive"], "different independently sealed stock-writer SDK archive")
    packed = root / "placement-sdk.tar.zst"
    with zipfile.ZipFile(outer) as z:
        need(
            sorted(z.namelist()) == ["placement-sdk.tar.zst", "seal.json"]
            and z.getinfo("seal.json").file_size < 8192,
            "unexpected SDK transport layout",
        )
        seal = json.loads(z.read("seal.json"))
        need(
            seal["factory_run"] == FACTORY
            and seal["qa"] == FACTORY_QA
            and seal["candidate"] == reg["roles"]["C"]["revision"]
            and seal["bytes"] == z.getinfo("placement-sdk.tar.zst").file_size < 768 << 20,
            "incorrect content address",
        )
        with z.open("placement-sdk.tar.zst") as inp, packed.open("xb") as out:
            shutil.copyfileobj(inp, out)
    need(sha(packed) == seal["sha256"], "altered matched stage1 archive")
    names = set()
    total = 0
    with subprocess.Popen(["zstd", "-qdc", packed], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
            for item in tf:
                rel = Path(item.name)
                need(
                    not rel.is_absolute()
                    and ".." not in rel.parts
                    and str(rel) == item.name
                    and item.name not in names
                    and rel.parts[0] in ("capsule", "documentation", "logs"),
                    "unsafe constructor member",
                )
                names.add(item.name)
                where = root / rel
                if item.isdir():
                    where.mkdir(parents=True, exist_ok=True)
                    continue
                need(
                    item.isreg() and 0 < item.size < 700 << 20 and item.mode & 0o7000 == 0,
                    "nonregular or oversized constructor member",
                )
                total += item.size
                need(total < 3 << 30, "excess constructor archive")
                where.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(item) as inp, where.open("xb") as out:
                    shutil.copyfileobj(inp, out)
                where.chmod(item.mode & 0o777)
        need(proc.wait() == 0, "truncated compressed kit")
    logs = root / "logs"
    need(seal["factory"] == sha(logs / "factory.json"), "wrong factory result")
    factory = json.loads((logs / "factory.json").read_bytes())
    need(
        factory["roles"] == reg["roles"]
        and factory["qualified"] == sha(root / "capsule/qualified.json")
        and factory["registration"] == sha(scope.HERE / "registration.json"),
        "source registration differs",
    )
    capsule.reopen(root / "capsule", root / "parked")
    manifests = capsule.admit(root / "capsule")
    docs = {}
    physical = {}
    for role, label in (("P", "normal"), ("C", "defer")):
        built = json.loads((logs / (role + "-constructed.json")).read_bytes())
        need(
            built["source"] == reg["roles"][role]
            and set(built["rustc_crates"]) == set(CRATES)
            and all(built["rustc_crates"].values())
            and built["cxx"]["OhmRegisterCoalescer.cpp"]
            and bool(built["cxx"]["OhmSourcePlacement.cpp"]) == (role == "C")
            and sha(logs / (role + "-constructors.jsonl.gz")) == built["native_selection"],
            "incomplete physical compiler construction",
        )
        park = root / "parked" / label
        doc = root / "documentation" / role / "rustdoc"
        proof = json.loads((logs / (role + "-docs.json")).read_bytes())
        need(
            proof["source"] == reg["roles"][role]["revision"]
            and proof["rustdoc"] == factory["docs"][role]
            and [sha(doc), doc.stat().st_size, stat.S_IMODE(doc.stat().st_mode)]
            == proof["rustdoc"],
            "incorrect role documentation",
        )
        doc.chmod(0o555)
        d = root / "doc-products" / role
        d.mkdir(parents=True)
        os.link(doc, d / "rustdoc")
        os.link(doc, park / "bin/rustdoc")
        version = subprocess.check_output(
            [park / "bin/rustdoc", "-vV"],
            env={"PATH": "/usr/bin:/bin", "LD_LIBRARY_PATH": str(park / "lib")},
            text=True,
        )
        docs[role] = proof | {"version": version}
        driver = factory["physical"][role]["driver"]
        need(
            manifests[role][driver["member"]][0]
            == sha(park / driver["member"])
            == driver["sha256"],
            "different actual compiler DSO",
        )
        physical[role] = {"driver": driver["sha256"]}
    save(
        root / "source-qualification.json",
        {
            "factory_run": FACTORY,
            "factory_qa": FACTORY_QA,
            "archive": row,
            "seal": seal,
            "physical": physical,
            "source": reg["roles"],
            "qualified": sha(root / "capsule/qualified.json"),
        },
    )
    save(root / "docs-qualification.json", {"actual": docs})
    logs.rename(root / "source-receipts")

    candidate_cpp = json.loads((scope.HERE / "source-packet.json").read_bytes())["physical_files"][
        scope.stock_source.CPP
    ]["selected"]["sha256"]
    witnessed = json.loads((root / "source-receipts/C-constructed.json").read_bytes())["cxx"][
        "OhmSourcePlacement.cpp"
    ]
    need(
        witnessed and all(v["sha256"] == candidate_cpp for v in witnessed),
        "actual C++ constructor differs from the guarded source",
    )


def main(destination, include_prior):
    import kits as prior_receiver

    scope.bind()
    with scope.product("Stock4") as current:
        install(destination, current)
    if include_prior:
        with scope.product("C3b") as prior:
            prior_receiver.install(destination.with_name("placement-previous-sdks"), prior)


if __name__ == "__main__":
    choice = sys.argv[2:]
    need(choice in ([], ["with-prior"]), "invalid SDK placement")
    main(Path(sys.argv[1]), bool(choice))
