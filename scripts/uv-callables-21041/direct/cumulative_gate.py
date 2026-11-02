"""Enforce the two authentic predecessor jobs and the direct comparison before calibration."""
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import median
import uuid


CONTROL = "stock_ctfe318"
CANDIDATE = "callables_ctfe318_incoherent_domain_proc_derive_trait_origin"
ROLES = [CONTROL, CANDIDATE]
P = "10d56274a98801b5ef8f80aab734e835749458e1"
PC = "ac67101cb973e35ce8ff044cc8014c2c76bab69e"
C = "e4edbdd943f2ceac098ddde880e8f97a3bb3270f"
TREES = ("1a0e58a855e1782a93cdf8c56b337fb4354142ef", "8fdc0aa6f4833c25814f97056ed639212e53b6d5")
DRIVERS = ("165ecb764f6ea877c24b8620243a0ad31376fbf45d5a44e853638f1375da05e2", "b179c2694c8daf8746deb637e96dd06f4e4f6ad1cbee9fdcd7245cc1720f9b50")
SOURCE = "1c09d403e702da036a80a1d4ac54937b57bde9ad"
MARGINAL = "0aecea4345b011433b5f65daf055a924946605ae"
MARGINAL_PAIR = "05da3145fde2e38d09bf33331b79acd8bc1e16d2160bb10a8d3ee8017069849f"
MARGINAL_RUN = 41473622846
MARGINAL_JOB = 125373342351
MARGINAL_BOOT = "e324c8e4-393e-406c-89b9-c90541c6a55f"
MARGINAL_BOOT_ZIP = "c3ad1513cf0705c80335130ad62e1f6fe73306279fb07d4133c943cf4507096c"
MARGINAL_BOOT_MEMBER = "efb0ade440ae4224a0f380f54cb3fce336ecbd8a5af496baf9fb9f7a7a564ca4"
BUILD_HEAD = "9394353530e46adc4bcf696c6d8ded8ef2c65a87"
BUILD_RUN = 41475005437
BUILD_JOB = 125378137837
BUILD_BOOT = "25cdc504-4b06-4552-b328-3e645d69a37b"
BUILD_BOOT_ZIP = "03672e258fa01ade185d34ed5d8aa04572269b0a55b020c7fd21b0acda1544fd"
BUILD_BOOT_MEMBER = "392bb1569abaffb7c2dc174701cc5fe7d44c27ad88ea458940572e3d9b2f5d9f"
LOCAL_BOOT = "5a939a53-79ef-4ab0-8ada-c57a788992d3"
LOCAL_PHYSICAL = "70f9faa511a78b113a78bf2bb4fcc01394ebd1f55906eceeb7a49834d3d115f6"
PLAN = "1fb72a1d2dee05a85207f1e3a1898c9aca68a74152bf74886aff11ca1dfe7c0c"
MIGRATION = "225e9797a5f94eebfbf0cc0feb01b39cfc371e876fbff4cd6df27fc70318ce31"
PILOT = "7ab4625730617568216f6297ce10e2d59196d9fcc85fa637d33c017e82ac8742"
CARGO = "3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871"
CRATES = frozenset(("uv_cache", "uv_client", "uv_configuration", "uv_distribution_types", "uv_install_wheel", "uv_metadata", "uv_pypi_types", "uv_torch"))
BRANCH = "charlie/codex-21041-trait-origin-cumulative-check"
ORDERS = ["PC", "CP", "CP", "PC"] * 2


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def require(ok, why):
    if not ok:
        raise ValueError(why)


def evidence(rows):
    require(len(rows) == 8 and all(len(pair) == 2 and all(type(x) is int and x > 0 for x in pair) for pair in rows), "eight genuine positive pairs required")
    ratios = [Fraction(c, p) for p, c in rows]
    return ratios, [median(ratios[:4]), median(ratios[4:])]


def entry(kind, r):
    require(r["kind"] == kind and r["source_pair"] == [PC, C] and r["repository"] == "astral-experiments/ohm" and r["repository_id"] == 1319437234, "different predecessor or sources")
    require(r["attempt"] == 1 and r["successful_private_service"] is True and r["native_replay_passed"] is True and r["independent_A_seeds"] == 16, "predecessor has no complete service and native evidence")
    require(type(r["run"]) is int and type(r["job"]) is int and r["run"] > 0 and r["job"] > 0 and re.fullmatch("[0-9a-f]{40}", r["head"]), "incomplete service origin")
    require(str(uuid.UUID(r["boot"])) == r["boot"] and set(r["archives"]) == {"raw", "boot"} and len({item["id"] for item in r["archives"].values()}) == 2, "missing or unbound predecessor boot")
    for item in r["archives"].values():
        require(type(item["id"]) is int and item["id"] > 0 and type(item["bytes"]) is int and item["bytes"] > 0 and re.fullmatch("[0-9a-f]{64}", item["sha256"]), "invalid observed service artifact")
    require(all(re.fullmatch("[0-9a-f]{64}", r[k]) for k in ("native_replay_sha256", "raw_verdict_sha256", "boot_member_sha256", "calibration", "full_registration")), "incomplete native proof")
    ratios, halves = evidence(r["raw_parent_candidate"])
    if kind == "marginal":
        require(r["head"] == MARGINAL and r["full_registration"] == MARGINAL_PAIR and r["native_rustc_records"] == 128 and r["typed_products"] == 37, "wrong marginal protocol")
        require((r["run"],r["job"],r["boot"],r["boot_member_sha256"]) == (MARGINAL_RUN,MARGINAL_JOB,MARGINAL_BOOT,MARGINAL_BOOT_MEMBER) and r["archives"]["boot"] == {"id":13155927459,"bytes":879,"sha256":MARGINAL_BOOT_ZIP},"different initial marginal machine or service original")
        require(all(x < Fraction(996, 1000) for x in ratios + halves), "production marginal did not clear the preregistered threshold")
    elif kind == "linked_build":
        require(r["true_build"] == ["build", "--locked", "--offline", "-j8", "-p", "uv-cli"] and r["full_registration"] == "ea0469db52be561571e66b34025bfe8f13c5e81c2740300e4c8c3ca58a28bf51", "wrong linked-build protocol")
        require((r["run"],r["head"],r["job"],r["boot"],r["boot_member_sha256"]) == (BUILD_RUN,BUILD_HEAD,BUILD_JOB,BUILD_BOOT,BUILD_BOOT_MEMBER) and r["archives"]["boot"] == {"id":13157116972,"bytes":1707,"sha256":BUILD_BOOT_ZIP},"different accepted #20992 measurement registration or machine")
        require(sum(x < Fraction(11, 10) for x in ratios) >= 7 and all(x < Fraction(21, 20) for x in halves), "ordinary linked-build guard rejected")
    else:
        raise ValueError("unknown entry condition")


def wall(values):
    ratios, _ = evidence(values)
    factors = [1 / r for r in ratios]
    halves = [median(factors[:4]), median(factors[4:])]
    return {"parent_over_candidate": list(map(str, factors)), "median_parent_over_candidate": str(median(factors)), "half_medians": list(map(str, halves)),
            "faster_pairs": sum(r > 1 for r in factors), "twofold_pairs": sum(r > 2 for r in factors),
            "repeatable_wall_improvement_on_this_worker": sum(r > 1 for r in factors) >= 7 and min(halves) > 1,
            "all_eight_twofold_on_this_worker": all(r > 2 for r in factors), "independent_twofold_wall_replication_required": True}


def admit(here, study, pair):
    folder = here / "direct"
    plan = read(here / "measurement-plan.json")
    require(pair.get("enrolled") is True, "closed until both separate hardware jobs and their native receivers pass")
    require(sha(here / "pair.json") == study["sdk_lock_sha256"] and sha(here / "measurement-plan.json") == study["measurement_plan_sha256"] == pair["measurement_plan_sha256"] == PLAN, "changed source, pair or prospective rules")
    require(plan["fixed_signed_cargo_sha256"] == CARGO and [arm["commit"] for arm in plan["compilers"]] == [P, C] and plan["command"] == ["cargo", *study["score_commands"]], "wrong signed Cargo or measured command")
    require(sha(folder / "direct-native.json") == MIGRATION and read(folder / "direct-native.json")["compilers"] == [[P, 43310], [C, 43323]], "missing actual source-paired migration")
    require(pair["roles"] == study["roles"] == ROLES and pair["format_versions"] == {"incremental": [43310, 43323], "metadata": [3, 43319]}, "wrong role or formats")
    require(study["parent"] == SOURCE and study["branch"] == BRANCH and study["independent_holds"] == [0]*4+[1]*4, "wrong carrier or holds")
    require(study["orders"] == [[ROLES[int(c == "C")] for c in x] for x in ORDERS] and set(study["edited_workspace_roster"]) == CRATES and len(study["native_workspace_units"]) == 37, "changed orders or incomplete work")
    require(study["mode_orders"] == read(folder / "modes.json") and sha(folder / "modes.json") == pair["modes_sha256"], "changed restored measurement order")
    for role, rev, tree, driver, epoch, pkg in zip(ROLES, (P, C), TREES, DRIVERS, (43310, 43323), (13112756183, 13151202059), strict=True):
        a = pair["arms"][role]
        require((a["source"]["commit"], a["source"]["tree"], a["source"]["epoch"], a["driver"],a["artifact"]["id"]) == (rev, tree, epoch, driver, pkg), "wrong production distribution")
        inv = folder / (role + "-runtime.json")
        require(sha(inv) == pair["inventories"][role] and len(read(inv)) == 142 and read(inv)["bin/cargo"] == CARGO, "unbound complete installed SDK")
    packet = folder / "entries.json"
    require(sha(packet) == pair["entries_sha256"], "changed entry outcomes")
    entries = read(packet)
    require(set(entries) == {"marginal", "linked_build"}, "missing production gate")
    boots = {v["boot"] for v in pair["prior_boots"].values()}
    require(len(boots) == len(pair["prior_boots"]) >= 23 and len({r["boot"] for r in entries.values()}) == 2, "lost or reused a physical boot")
    for key, record in entries.items():
        entry(key, record)
        boot = pair["prior_boots"][str(record["run"])]
        require(boot["boot"] == record["boot"] and boot["head"] == record["head"] and boot["job"] == record["job"] and boot["boot_member_sha256"] == record["boot_member_sha256"], "entry machine not excluded")
    prior = read(folder / "earlier-boots.json")
    require(len(prior) == 20 and all(pair["prior_boots"].get(k) == item for k, item in prior.items()), "changed the original known host exclusions")
    local=pair["prior_boots"]["local-20992"]
    require(local["boot"]==LOCAL_BOOT and local["physical_sha256"]==sha(folder/"local-pilot-physical.json")==LOCAL_PHYSICAL and read(folder/"local-pilot-physical.json")["boot"]==LOCAL_BOOT,"lost the local preflight host")
    first=read(folder/"marginal-boot-origin.json")
    require((first["sha256"],first["entry_sha256"],first["artifact_id"],first["job"],first["run"],first["boot"]) == (MARGINAL_BOOT_ZIP,MARGINAL_BOOT_MEMBER,13155927459,MARGINAL_JOB,MARGINAL_RUN,MARGINAL_BOOT), "lost accepted marginal early original")
    second=read(folder/"build-boot-origin.json")
    require((second["archive_sha256"],second["entry_sha256"],second["artifact_id"],second["job"],second["run"],second["boot"]) == (BUILD_BOOT_ZIP,BUILD_BOOT_MEMBER,13157116972,BUILD_JOB,BUILD_RUN,BUILD_BOOT),"lost accepted #20992 early original")
    material = read(here / "derive/cumulative-material.json")
    require(material["source_coordinator"][CANDIDATE] == MARGINAL and material["source_coordinator"][CONTROL] == "125cef4f90f572d8a8d19da42b0bc2b1fcae87a8", "wrong byte-verified intake readers")
    require(material["services"] == {r:pair["arms"][r]["service"] for r in ROLES} and sha(here / "derive/cumulative-material.json") == pair["cumulative_material_sha256"], "wrong producer service input")


def all_installed(pool, folder, pair, filehash):
    for role in ROLES:
        recorded = folder / (role + "-runtime.json")
        require(sha(recorded) == pair["inventories"][role], "changed installed SDK inventory")
        wanted = read(recorded)
        base = pool / role
        actual = {p.relative_to(base).as_posix():filehash(p) for p in base.rglob("*") if p.is_file()}
        require(len(actual) == 142 and actual == wanted, "installed physical SDK differs from the original qualified 142 files")
