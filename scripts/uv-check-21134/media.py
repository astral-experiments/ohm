"""Read the original signed release from Releases and original G/F production ZIPs from Actions."""

from pathlib import Path
import hashlib, json, os, re, shutil, subprocess, sys, zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

OLD = SCRIPTS / "uv-client-22958"
LOCKFILE = OLD / "signed-23-split-lock.json"
FLOCK = read(LOCKFILE)
G = read(HERE / "G-source.json")
REPO = "astral-experiments/ohm"
GBRANCH = "charlie/codex-21134-handwritten-production23"
GSDK = "rc23-21134-sdk-G"
GQA = "rc23-21134-qa-G-attempt-1"
require(
    sha(LOCKFILE) == P["roles"]["F"]["release_lock"]
    and G["commit"] == P["roles"]["G"]["rust"]
    and G["parent"] == P["roles"]["F"]["rust"]
    and G["tree"] == P["roles"]["G"]["tree"],
    "G source or prior F",
)


def gh(*args):
    require(os.environ.get("GITHUB_ACTIONS") == "true", "live GitHub transport is hosted-only")
    return subprocess.run(["gh", *args], check=True, stdout=subprocess.PIPE).stdout


def download_args(endpoint):
    prefix = f"repos/{REPO}/"
    if re.fullmatch(prefix + r"actions/artifacts/[1-9][0-9]*/zip", endpoint):
        return ["api", endpoint]
    require(re.fullmatch(prefix + r"releases/assets/[1-9][0-9]*", endpoint), "unknown binary API route")
    return ["api", "-H", "Accept: application/octet-stream", endpoint]


class Transport:
    @staticmethod
    def gh_json(*args):
        return json.loads(gh(*args))

    @staticmethod
    def gh_bytes(endpoint, target, size, sha256):
        require(os.environ.get("GITHUB_ACTIONS") == "true", "hosted binary transport only")
        require(not target.exists(), "immutable raw service file")
        with target.open("xb") as out:
            subprocess.run(["gh", *download_args(endpoint)], stdout=out, check=True)
        require(blob(target) == [size, sha256], "wrong Actions ZIP or release asset")


def result_sources(run, jobs, arts):
    g = G
    good = (run["id"], run["head_sha"])
    require(
        run["repository"]["id"] == run["head_repository"]["id"] == 1319437234
        and run["id"] == 41590680452
        and run["head_sha"] == "aecbf860cfee7523292d41c38a5e397567895074"
        and run["head_branch"] == GBRANCH
        and run["run_attempt"] == 1
        and run["event"] == "workflow_dispatch"
        and run["status"] == "completed"
        and run["conclusion"] == "success",
        "wrong actual G producer",
    )
    names = {x["name"]: x for x in arts["artifacts"]}
    require(
        set(names) == {GSDK, GQA} and len(names) == arts["total_count"],
        "expected only original G SDK plus QA",
    )
    require(
        len(jobs["jobs"]) == jobs["total_count"]
        and all((j["run_id"], j["head_sha"]) == good and j["run_attempt"] == 1 for j in jobs["jobs"]),
        "wrong producer jobs",
    )
    for n, a in names.items():
        r = a["workflow_run"]
        require(
            (r["id"], r["head_sha"]) == good
            and r["repository_id"] == r["head_repository_id"] == 1319437234
            and a["size_in_bytes"] > 0
            and a["digest"].startswith("sha256:"),
            "wrong Actions artifact origin",
        )
    return names


def g_zip_pair(sdkzip, qazip, out=None):
    with zipfile.ZipFile(sdkzip) as z, zipfile.ZipFile(qazip) as qa:
        names = {
            "ohm.tar.gz",
            "role.json",
            "source.json",
            "component-inventory.json",
            "sdk-inventory.json",
            "SHA256SUMS",
        }
        require(set(z.namelist()) == names and len(z.namelist()) == len(names), "G artifact members")
        d = {n: z.read(n) for n in names - {"ohm.tar.gz"}}
        checks = {k: h for h, k in (x.split(None, 1) for x in d["SHA256SUMS"].decode().splitlines())}
        require(
            set(checks) == names - {"SHA256SUMS"}
            and all(hashlib.sha256(d[n]).hexdigest() == checks[n] for n in d if n in checks),
            "checksummed G inputs",
        )
        src = json.loads(d["source.json"])
        role = json.loads(d["role.json"])
        inventory = json.loads(d["sdk-inventory.json"])
        require(
            src["source"] == G
            and role["role"] == "G"
            and role["source_sha256"] == checks["source.json"]
            and role["archive_sha256"] == checks["ohm.tar.gz"],
            "G source/role/SDK",
        )
        require(
            [role[k] for k in ("source_commit", "source_tree", "epoch", "metadata_epoch")]
            == [G[k] for k in ("commit", "tree", "epoch", "metadata_epoch")],
            "G native source or format",
        )
        require(
            role["execution_pgo"]
            and role["bolt_note"]
            and role["native_unit_and_runmake"]
            and role["installed_runmake"][G["run_make"]]["linked_outputs"] == G["linked_outputs"],
            "G native/optimization evidence",
        )
        for n in ("role.json", "source.json"):
            require(qa.read("capacity/" + n) == d[n], "QA/SDK independent source disagreement")
        raw = inventory["files"] if "files" in inventory else inventory
        require(
            len(raw) == 142
            and set(FLOCK["raw"]["F"]) - set(raw)
            <= set(k for k in FLOCK["raw"]["F"] if k.startswith(("lib/", "libexec/"))),
            "G raw native package members",
        )
        with z.open("ohm.tar.gz") as f:
            if out:
                with out.open("xb") as o:
                    shutil.copyfileobj(f, o, 1 << 20)
                checksum = sha(out)
            else:
                checksum = hashlib.file_digest(f, "sha256").hexdigest()
        require(checksum == checks["ohm.tar.gz"], "G original inner SDK")
        return {
            "sources_sha256": checks["source.json"],
            "role_sha256": checks["role.json"],
            "raw": raw,
            "archive_sha256": checksum,
            "archive_bytes": z.getinfo("ohm.tar.gz").file_size,
        }


def enroll(original, qualified, out):
    require(not out.exists(), "existing enrollment")

    def table(k):
        return read(original / (k + ".json"))

    run = table("run")
    jobs = table("jobs")
    arts = table("artifacts")
    names = result_sources(run, jobs, arts)
    zips = {n: original / (n + ".zip") for n in names}
    for n, z in zips.items():
        require(blob(z) == [names[n]["size_in_bytes"], names[n]["digest"][7:]], "unbound original " + n)
    archive = g_zip_pair(zips[GSDK], zips[GQA])
    q = read(qualified / "qualified.json")
    effective = read(qualified / "effective-inventory.json")
    require(
        q["source"] == G
        and q["signed_cargo"] == FLOCK["signed_cargo_row"]
        and q["effective_inventory"] == sha(qualified / "effective-inventory.json")
        and q["effective_members"] == len(effective) == 142,
        "G native physical qualifier",
    )
    require(effective == archive["raw"] | {"bin/cargo": FLOCK["signed_cargo_row"]}, "actual installed hashes")
    require(
        q["incremental"] == sha(qualified / "cache-transition/passed.json")
        and q["rmeta"] == sha(qualified / "metadata-transition/passed.json")
        and q["native_readers"],
        "actual format migration",
    )
    val = {
        "G": archive,
        "G_qualified": sha(qualified / "qualified.json"),
        "G_physical": q,
        "G_effective": canonical({k: v["sha256"] for k, v in effective.items()}),
        "migrations": {"incremental": q["incremental"], "rmeta": q["rmeta"]},
        "F_lock": sha(LOCKFILE),
        "source": G,
        "protocol": sha(HERE / "protocol.json"),
        "action": {
            "run": run["id"],
            "head": run["head_sha"],
            "branch": run["head_branch"],
            "jobs": [j["id"] for j in jobs["jobs"] if j["conclusion"] == "success"],
            "artifacts": {
                n: {k: v[k] for k in ("id", "name", "digest", "size_in_bytes")} for n, v in names.items()
            },
        },
    }
    require(val["action"]["jobs"], "no successful original job")
    save(out, val)
    return val


def authorize(lock):
    require(
        lock["protocol"] == sha(HERE / "protocol.json")
        and lock["F_lock"] == sha(LOCKFILE)
        and lock["source"] == G
        and lock["G_physical"]["source"] == G
        and lock["action"]["branch"] == GBRANCH
        and set(lock["action"]["artifacts"]) == {GSDK, GQA},
        "G qualification is not enrolled here",
    )
    require(
        len(lock["G"]["raw"]) == 142
        and lock["G_effective"]
        == canonical(
            {k: v["sha256"] for k, v in (lock["G"]["raw"] | {"bin/cargo": FLOCK["signed_cargo_row"]}).items()}
        ),
        "G native material roster",
    )


def installed(out, tmp, control, lock):
    authorize(lock)
    os.environ["UV_22958_CONTRAST"] = "signed"
    sys.path.insert(0, str(OLD))
    import service as old, release_intake as sdk, release23_package as package

    proof = out / "intake"
    proof.mkdir()
    temp = tmp / "raw-sdk-21134"
    temp.mkdir()
    pool = tmp / "installed-21134"
    pool.mkdir()
    official = package.official(Transport, proof, temp)
    cargo = sdk.signed_cargo(official, temp / "signed-cargo")
    archive = official
    if control == "F":
        orig = proof / "production-F"
        orig.mkdir()
        archive = package.production("F", Transport, orig, temp)
    sdk.install_archive(archive, pool / control, control)
    shutil.copy2(cargo, pool / control / "bin/cargo")
    ident = {control: sdk.role_sdk(control, pool / control, proof / ("material-" + control))}
    base = "repos/" + REPO + "/actions/runs/" + str(lock["action"]["run"])
    rest = [Transport.gh_json("api", base + s) for s in ("", "/jobs?per_page=100", "/artifacts?per_page=100")]
    require(
        rest[0]["head_sha"] == lock["action"]["head"]
        and [j["id"] for j in rest[1]["jobs"] if j["conclusion"] == "success"] == lock["action"]["jobs"],
        "different G production service",
    )
    names = result_sources(*rest)
    for k, row in zip(("run", "jobs", "artifacts"), rest):
        save(proof / ("G-" + k + ".json"), row)
    for name, spec in lock["action"]["artifacts"].items():
        v = names[name]
        require(not v["expired"] and spec == {k: v[k] for k in spec}, "wrong G Actions retrieval")
        Transport.gh_bytes(
            "repos/" + REPO + "/actions/artifacts/" + str(v["id"]) + "/zip",
            temp / (name + ".zip"),
            v["size_in_bytes"],
            v["digest"][7:],
        )
    archive = temp / "G-compiler.tar.gz"
    require(
        g_zip_pair(temp / (GSDK + ".zip"), temp / (GQA + ".zip"), archive) == lock["G"],
        "G archive before extraction",
    )
    # The inherited installer verifies all raw manifest members, modes and native binaries again.
    source = {k: G[k] for k in ("commit", "epoch", "metadata_epoch", "tree")}
    old.lock["raw"]["G"] = lock["G"]["raw"]
    old.lock["effective_hashes"]["G"] = lock["G_effective"]
    old.SOURCES["G"] = source
    sdk.install_archive(archive, pool / "G", "G")
    shutil.copy2(cargo, pool / "G/bin/cargo")
    ident["G"] = sdk.role_sdk("G", pool / "G", proof / "material-G")
    save(out / "installed.json", ident)
    return pool


if __name__ == "__main__":
    require(len(sys.argv) == 5 and sys.argv[1] == "enroll", "enroll ORIGINAL_G_DIR QUALIFIED_G_DIR OUTPUT")
    enroll(*map(Path, sys.argv[2:]))
