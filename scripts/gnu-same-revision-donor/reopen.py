"""Independently reopen the actual commands, test inventories and source-qualified driver overlay."""

import argparse
import json
import re
import stat
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binding as reg
from bootstrap_subject import unit_log
import overlay
import transplant

CARGO = "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4"
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
WILD_PATH = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
STAGE0 = {
    "source": "759b73eca37a7b589b1ecc0fea77d94a1f8ca36cddb94f1401c72343e0dc1d4e",
    "rustc": "3690cc576ede140504698405d5d8fa3826aaadbe71699c6c4ed0a565d6f493e2",
    "cargo": "ff3022fcbd13b08434ea7afde9a0ef9d5b3f5c17b5fc7a40031be3ee000a6a24",
}
LLVM = "fba1b05a7bd8bdc73080edd02f672cef44648267"
E_DRIVER = "f20d40da3f9365b0d3544ad76136e8c1036a6d1a5ecb39281e972f782fa33ae6"
D_DRIVER = "f724a33d4d865ac4f3fc235b322a638d6f6534f669e5b1659adabcd04a2221d7"


def load(p):
    return json.loads(p.read_bytes())


def command(folder, name, expected, cwd, status=(0,)):
    body = (folder / (name + ".log")).read_bytes()
    cmd = load(folder / (name + ".command.json"))
    reg.need(
        cmd["argv"] == expected
        and cmd["cwd"] == cwd
        and cmd["returncode"] in status
        and cmd["output_sha256"] == reg.digest(body),
        "wrong source command or raw log: " + name,
    )
    return re.sub(r"\x1b\[[0-9;]*m", "", body.decode(errors="strict"))


def native_pass(body, case):
    rows = [line for line in body.splitlines() if line.startswith("test [run-make] ")]
    reg.need(
        rows == ["test [run-make] tests/run-make/" + case + " ... ok"]
        and body.splitlines().count("running 1 tests") == 1
        and re.search(r"^test result: ok\. 1 passed; 0 failed; 0 ignored;", body, re.M)
        and "internal compiler error" not in body,
        "missing actual run-make " + case,
    )


def host_contact(raw, logs, parked):
    proof = load(raw / "host-entry/fanotify.json")
    records = {Path(f["path"]).name: f for f in proof["registered"]}
    reg.need(
        set(records) == {"a", "a-hardlink", "b"}
        and len(proof["registered"]) == 3
        and proof["exit"] == 0
        and proof["stdout"] == b"original-A".hex() + "\n"
        and re.fullmatch("[0-9a-f-]{36}", proof["boot"]),
        "foreign host file-open contact",
    )
    true = records["a"]
    other = records["b"]
    reg.need(
        all(records["a-hardlink"][k] == true[k] for k in ("dev", "ino", "length", "sha256"))
        and true["ino"] != other["ino"]
        and true["sha256"] == reg.digest(b"original-A")
        and other["sha256"] == reg.digest(b"unread-B")
        and all(
            (e["pid"], e["dev"], e["ino"], e["length"])
            == (proof["child"], true["dev"], true["ino"], 10)
            for e in proof["events"]
        )
        and all(any(e["mask"] & flag for e in proof["events"]) for flag in (32, 1, 16)),
        "incorrect native hardlink/foreign PID",
    )
    if parked:
        reg.need(
            Path("/proc/sys/kernel/random/boot_id").read_text().strip() == proof["boot"],
            "file-open contact from a different host",
        )
    group = logs / "donor-fixtures/group/group-v2/qualified.json"
    if group.exists():
        checked = load(group)
        reg.need(
            checked["schema"] == 3 and checked["boot"] == proof["boot"],
            "file/exec observer boots differ",
        )
    return proof["boot"]


def verify(raw, logs, parked):
    recorded_boot = host_contact(raw, logs, parked)
    native = raw / "P"
    src = load(native / "native-qualified.json")
    baseline = load(raw / "P/source.json")
    source = load(HERE / "inputs/product.json")
    reg.need(
        reg.sha(HERE / "inputs/product.json") == reg.SOURCE_RECEIPT
        and baseline["product"] == source
        and baseline["previous"] == reg.OLD
        and baseline["llvm"] == src["llvm"] == LLVM
        and src["stage0"] == STAGE0
        and (src["old"], src["new"], src["tree"]) == (reg.OLD, reg.NEW, reg.TREE),
        "wrong native product source",
    )
    records = {r: load(logs / "sdk" / (r + ".json")) for r in ("D", "P")}
    reg.need(
        records["D"]["source"] == reg.OLD
        and records["P"]["source"] == reg.NEW
        and all(records[r]["role"] == r for r in records),
        "wrong D or P SDK source receipt",
    )
    ids = {
        r: {p: [x[0], x[4], x[3]] for p, x in record["files"].items()}
        for r, record in records.items()
    }
    driver = src["driver"]
    old_e = load(logs / "sdk/E.json")
    epsilon = {n: [v[0],v[4],v[3]] for n,v in old_e["files"].items()}
    reg.need(old_e["source"]["role"]["commit"] == reg.ORIGINAL and old_e["role"] == "E"
             and old_e["driver"] == driver and len(epsilon) == 81 and epsilon.keys() == ids["D"].keys()
             and {n for n in epsilon if epsilon[n] != ids["D"][n]} == {driver}
             and epsilon[driver][0] == E_DRIVER, "incorrect original E-to-D overlay closure")
    transplant.prior_suite((logs / "sdk/donor-incremental.log").read_bytes())
    reg.need(
        all(
            len(rows) == 81
            and rows["bin/cargo"][0] == CARGO
            and rows[WILD_PATH][0] == WILD
            and records[r]["driver"] == driver
            for r, rows in ids.items()
        )
        and ids["D"][driver][0] == D_DRIVER
        and src["old_driver"] == ids["D"][driver]
        and src["new_driver"] == ids["P"][driver],
        "incorrect locked compiler SDK, Cargo or Wild",
    )
    reg.need(
        overlay.verify(native / "overlay", ids["D"], ids["P"], driver) == src["overlay"],
        "missing verified decompressed driver",
    )
    spec = load(HERE / "inputs/bootstrap.json")
    argv, cwd = spec["argv"], spec["cwd"]
    reg.need(src["bootstrap"] == argv and argv.count("build") == 1, "changed literal bootstrap")
    stage = argv.index("build")
    cli = (
        argv[:stage]
        + ["--set", "rust.verbose-tests=true", "test"]
        + argv[stage + 1 : argv.index("compiler/rustc")]
    )
    command(native, "bootstrap", argv, cwd)
    command(native, "reassemble", argv, cwd)
    reg.need(
        src["units"]
        == unit_log(
            command(native, "incremental", cli + ["--tests", "compiler/rustc_incremental"], cwd)
        )
        and src["run_make"] == list(reg.RUN_MAKE),
        "wrong compiler tests",
    )
    test_cmd = cli + ["--tests", "compiler/rustc_incremental"]
    transplant.outcomes(command(native, "incremental", test_cmd, cwd), False)
    transplant.outcomes(command(native, "parent-transplant", test_cmd, cwd, (1, 101)), True)
    transplant.outcomes(command(native, "restored-tests", test_cmd, cwd), False)
    evidence = load(native / "transplant-source.json")
    red_tests = (native / "transplanted-tests.rs").read_bytes()
    blobs = source["source"]["blobs"]
    reg.need(red_tests.endswith(transplant.SHIM)
             and reg.digest(red_tests[:-len(transplant.SHIM)]) == blobs[transplant.TESTS]["candidate"][1]
             and evidence == {"production":reg.OLD, "production_sha":blobs[transplant.PRODUCTION]["parent"][1],
                              "tests":reg.digest(red_tests),"literal_candidate_tests":blobs[transplant.TESTS]["candidate"][1],
                              "only_changed_from_D":[transplant.TESTS], "test":transplant.NAME},
             "red source differs from the exact old production and unedited new test")
    prior = load(logs / "sdk/donor-official.json")
    reg.need(baseline["old_job"] == prior and prior["run"] == 41303656721 and prior["job"] == 124839568474
             and prior["head"] == reg.CARRIER_PARENT and prior["original_workflow"] == "success"
             and prior["attempt"] == 1 and prior["artifacts"]["same-revision-donor-source-and-driver"]["digest"]
             == "sha256:130ae568b848980cf6ecc15e822439ada1f8cb44f758be0dae92421ac0806067",
             "different original D source")
    for case in reg.RUN_MAKE:
        native_pass(command(native, case, cli + ["tests/run-make/" + case], cwd), case)
    if parked:
        for role, rows in ids.items():
            root = (parked / role).resolve(strict=True)
            members = {
                str(f.relative_to(root))
                for f in root.rglob("*")
                if not f.is_dir() or f.is_symlink()
            }
            reg.need(members == set(rows), "missing or additional installed native member")
            for name, row in rows.items():
                f = root / name
                st = f.lstat()
                reg.need(
                    f.resolve(strict=True) == f
                    and stat.S_ISREG(st.st_mode)
                    and [reg.sha(f), st.st_size, stat.S_IMODE(st.st_mode)] == row
                    and [st.st_dev, st.st_ino] == records[role]["files"][name][1:3],
                    "different installed SDK: " + name,
                )
    return {
        "qualified": True,
        "source": [reg.OLD, reg.NEW, reg.TREE],
        "native_regression": {"parent": "None", "candidate": str(0xabcdef0123456789), "test":transplant.NAME},
        "prior_source_job": prior["job"],
        "bootstrap": argv,
        "stage0": src["stage0"],
        "llvm": src["llvm"],
        "drivers": [ids["D"][driver][0], ids["P"][driver][0]],
        "cargo": CARGO,
        "wild": WILD,
        "members": 81,
        "tested": src["units"] + src["run_make"],
        "overlay": src["overlay"],
        "physical_installation_reopened": bool(parked),
        "fanotify_boot": recorded_boot,
        "qa": src["qa"],
        "run": src["run"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source_receipts", type=Path)
    parser.add_argument("runner_logs", type=Path)
    parser.add_argument("parked", type=Path, nargs="?")
    args = parser.parse_args()
    print(json.dumps(verify(args.source_receipts, args.runner_logs, args.parked), sort_keys=True))
