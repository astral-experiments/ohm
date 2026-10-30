"""Measure native Cargo work after Ruff's real typeshed edit and verify its embedded ZIP."""
import argparse
import gzip
import io
import json
import zipfile
from pathlib import Path

from dyld import check as check_dyld
from execs import ExecTrace
from macho_paths import compare
from local_incremental import observed, preparation
from measure import capture, fresh, native_rows, retire, select
from native_inputs import run_archive_check
from prepare import prepare_ruff
from study import MISSING, RECHECK, compress_bytes, digest, env_for, git, need, run, save, sdk_id, sha, text_git
from verbs import macho_text
from fixed_crc import evidence

OLD = "ccba26cc3af909b7f19060f48f53daeab5070f9d"
NEW = "d8dac4cb576bd091a8b6cdc60a65c770ea75a96e"
TREES = {OLD: "1fd689cfa960a530bb3ee2b41b66078e997c6956", NEW: "3544d849218a624adac9e27b05f1f02a0d264457"}
LOCK = "583d2c16902903b32c016859c12131cb80fd8bdc4121440f359ef743675fc1c5"
ZLIB = "40990edd51aae2c2b6907af74ffb635029d5788228222c4bb811e9351c0caad3"
ZLIB_LIB = "58c4cfb06089f6e9e867afb7a6c05339df891dfe0afa107efb4c336f9266f049"
ACLE = "888122f712f7cacefe1e50d42b97ea0a3c5d6f32a5b4be632461a446ae1ed6da"
STUBS = ("source_commit.txt", "stdlib/typing.pyi", "stdlib/typing_extensions.pyi")
TESTS = ["tests::typeshed_vfs_consistent_with_vendored_stubs", "tests::typeshed_zip_created_at_build_time"]
BAD = "ohm_crc_missing_rust_name"
CMD = ["cargo", "+ohm", "test", "-p", "ty_vendored", "--lib", "--features", "deflate", "--no-run", "--locked", "--offline", "-j4", "--message-format=json"]
PHASES = [("cold", OLD), ("edit", NEW), ("repeat-1", NEW), ("repeat-2", NEW), ("invalid", NEW), ("repair", NEW)]


def identity(repo):
    need(text_git(repo, "rev-parse", "HEAD") == OLD and text_git(repo, "rev-parse", NEW+"^") == OLD, "wrong Ruff revisions")
    for rev, tree in TREES.items():
        need(text_git(repo, "rev-parse", rev+"^{tree}") == tree and digest(git(repo, "show", rev+":Cargo.lock")) == LOCK, "wrong source tree")
    files = git(repo, "diff", "--name-only", "-z", OLD, NEW).decode().strip("\0").split("\0")
    need(len(files) == 4 and all("crates/ty_vendored/vendor/typeshed/"+p in files for p in STUBS), "wrong Ruff edit")


def checkout(repo, rev, invalid=False):
    git(repo, "restore", "--source", rev, "--staged", "--worktree", "--", ".")
    need(text_git(repo, "write-tree") == TREES[rev] and not git(repo, "diff", "--name-only"), "Ruff checkout drift")
    if invalid:
        with (repo/"crates/ty_vendored/src/lib.rs").open("ab") as out:
            out.write(("\npub const OHM_CRC_INVALID: usize = " + BAD + ";\n").encode())


def keep(root, bucket, body):
    dest = root/"receipts"/bucket/(digest(body)+".gz")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        compress_bytes(dest, body)
    return dest


def zlib_units(artifacts, work, out):
    rows = []
    for unit in artifacts:
        if unit["target"]["name"] != "zlib_rs" or unit["target"]["kind"] != ["lib"]:
            continue
        source = Path(unit["target"]["src_path"])
        need(sha(source) == ZLIB_LIB and sha(source.parent/"crc32/acle.rs") == ACLE, "wrong zlib source")
        archive, = [Path(p) for p in unit["filenames"] if p.endswith(".rlib")]
        depname = archive.stem.removeprefix("lib")+".d"
        candidates = [p for d in (work/"shared",work/"target") for p in d.rglob(depname)]
        unique = {(p.stat().st_dev,p.stat().st_ino):p for p in candidates}
        dep, = unique.values()
        native = dep.read_bytes()
        need(b"zlib-rs-0.5.5/src/" in native, "wrong zlib dep-info")
        compress_bytes(out/("zlib-"+str(len(rows))+".dep.gz"), native)
        rows.append({"fresh":unit["fresh"], "path":str(archive), "sha256":sha(archive), "dep":digest(native),
                     "features":unit["features"], "hard":MISSING in native, "recheck":RECHECK in native})
    need(rows and len({r["path"] for r in rows})==len(rows), "missing or duplicate locked zlib units")
    return rows


def product(root, repo, rev, out, artifacts, messages, held=None):
    unit, = [r for r in artifacts if r["target"]["name"]=="ty_vendored" and r["profile"]["test"] and r["executable"]]
    exe = held[0] if held else Path(unit["executable"])
    bs, = [r for r in messages if r["reason"]=="build-script-executed" and "/ty_vendored#" in r["package_id"]]
    disk_zip = held[1] if held else Path(bs["out_dir"])/"zipped_typeshed.zip"
    archive = disk_zip.read_bytes()
    changed = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        need(z.testzip() is None and len(z.infolist())==len(set(z.namelist()))==819, "invalid typeshed ZIP")
        for name in STUBS:
            body = z.read(name)
            need(body==git(repo,"show",rev+":crates/ty_vendored/vendor/typeshed/"+name) and z.getinfo(name).compress_type==zipfile.ZIP_DEFLATED, "stale compressed Ruff input")
            changed[name] = digest(body)
    binary = exe.read_bytes()
    need(archive in binary, "actual returned executable does not contain this ZIP")
    keep(root,"crc-zips",archive)
    keep(root,"crc-programs",binary)
    cwd = repo/"crates/ty_vendored"
    listing = run([str(exe),"--list","--format","terse"],cwd=cwd)
    need(sorted(listing.decode().splitlines())==[n+": test" for n in TESTS], "unexpected libtest inventory")
    suite = run([str(exe),"--test-threads=1"],cwd=cwd)
    verdicts = sorted(line for line in suite.decode().splitlines() if line.startswith("test ") and " ... " in line)
    need(verdicts==["test "+n+" ... ok" for n in TESTS] and b"2 passed; 0 failed; 0 ignored" in suite, "wrong test verdict")
    compress_bytes(out/"test-list.gz",listing)
    compress_bytes(out/"test-suite.gz",suite)
    return str(exe), {**macho_text(exe), "zip_sha256":digest(archive), "inputs":changed, "tests":TESTS}


def phase(root, work, sdk, env, out, step, rev, trace):
    repo = root/"ruff"
    ok = step!="invalid"
    code, stdout, stderr, events, streams = capture(CMD, repo, env, out, trace)
    need(code==(0 if ok else 101), f"{step} returned {code}: {stderr[-500:]!r}")
    messages = [json.loads(s) for s in stdout.splitlines()]
    need(messages[-1]=={"reason":"build-finished","success":ok}, "missing Cargo terminal")
    arts = [r for r in messages if r["reason"]=="compiler-artifact"]
    native = native_rows(events,sdk)
    need(native["scope"]=="kernel-exec" and native["cargo"]==1 and all(x["stock"] for x in native["linkers"]), "incomplete kernel trace")
    observed(work, sdk, env, out, events, step)
    zlib = zlib_units(arts,work,out)
    # Cargo can report dirty before the native scheduler chooses a less expensive action.
    # Retain every typed row above and use the enrolled kernel compiler PIDs as the physical census.
    path = result = None
    argv = []
    if ok:
        path, result = product(root,repo,rev,out,arts,messages)
        argv = [link["argv"] for link in native["linkers"] if [b for a,b in zip(link["argv"],link["argv"][1:]) if a=="-o"]==[path]]
        if step in ("cold","clean","edit","repair"):
            need(len(argv)==1 and "ty_vendored" in native["full"], "required real edit/clean link was skipped")
    else:
        errors = [r["message"] for r in messages if r["reason"]=="compiler-message"]
        need(any((m.get("code") or {}).get("code")=="E0425" and BAD in m["message"] for m in errors) and
             not any(r["target"]["name"]=="ty_vendored" and r["executable"] for r in arts), "wrong invalid edit verdict")
    row = {"step":step,"rev":rev,"code":code,"command":CMD,"output":path,"product":result,"zlib":zlib,"native":native,"root_link_argv":argv,"streams":streams}
    evidence(work,out,row)
    save(out/"verified.json",row)
    print(step,rev[:8],len(native["full"]),len(native["linkers"]),len(argv),"zlib",native["full"].count("zlib_rs"),flush=True)
    return row


def installation(root, role, out, trace):
    work = root/"crc-work"
    work.mkdir(exist_ok=True)
    repo = root/"ruff"
    sdk = select(root,role)
    env = env_for(work,sdk)
    id_before = sdk_id(sdk,env)
    driver, = (sdk/"lib").glob("librustc_driver*.dylib")
    stat = driver.stat()
    save(out/"driver.json",{"role":role,"sdk":id_before,"dev":stat.st_dev,"ino":stat.st_ino,"ctime_ns":stat.st_ctime_ns})
    check_dyld(root,role,sdk,out/"dyld")
    results = {}
    for group, steps in (("clean-old",[("clean",OLD)]),("clean-new",[("clean",NEW)]),("visits",PHASES)):
        fresh(work,root/"seed")
        save(out/group/"initial-empty.json", preparation(work))
        previous = None
        result = {}
        for step,rev in steps:
            state = (rev, step=="invalid")
            if previous!=state:
                checkout(repo, *state)
            result[step] = phase(root,work,sdk,env,out/group/step,step,rev,trace)
            previous = state
        results[group] = result
        retire(work)
    after = driver.stat()
    need((stat.st_dev,stat.st_ino,stat.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_ctime_ns) and id_before==sdk_id(sdk,env), "compiler installation changed")
    refs = {rev:results[group]["clean"] for rev,group in ((OLD,"clean-old"),(NEW,"clean-new"))}
    need(refs[OLD]["product"]["zip_sha256"]!=refs[NEW]["product"]["zip_sha256"] and refs[OLD]["product"]["raw"]!=refs[NEW]["product"]["raw"], "historical edit did not change product")
    comparisons = {phase: row["product"] == refs[row["rev"]]["product"] for phase,row in results["visits"].items() if row["product"]}
    save(out/"own-clean-comparisons.json", comparisons)
    return refs, results["visits"]


def mechanism(root):
    trace = ExecTrace()
    try:
        trace.ready()
        top = root/"receipts/crc-comparison"
        for order in ("PC","CP"):
            clean, visits = {}, {}
            for role in order:
                clean[role], visits[role] = installation(root,role,top/order/role,trace)
            counts = {}
            for role, rows in visits.items():
                counts[role] = {k:{"rustcs":len(r["native"]["full"]),"ld":len(r["native"]["linkers"]),"root_ld":len(r["root_link_argv"]),
                                    "zlib_rustcs":r["native"]["full"].count("zlib_rs"),"hard":[u["hard"] for u in r["zlib"]],
                                    "recheck":[u["recheck"] for u in r["zlib"]]} for k,r in rows.items()}
            save(top/order/"physical.json",counts)
            for rev in (OLD,NEW):
                arms = {}
                for role in order:
                    row = clean[role][rev]
                    buf = gzip.decompress((root/"receipts/crc-programs"/(row["product"]["raw"]+".gz")).read_bytes())
                    need(digest(buf)==row["product"]["raw"], "wrong archived program")
                    arms[role] = buf,row["output"],row["root_link_argv"][0]
                save(top/order/("equivalence-"+rev+".json"),compare(arms))
            qualifies = all(counts["P"][k]["zlib_rustcs"]>0 and counts["P"][k]["root_ld"]==1
                            and counts["C"][k]["zlib_rustcs"]==counts["C"][k]["root_ld"]==0
                            and all(counts["P"][k]["hard"]) and not any(counts["C"][k]["hard"])
                            and all(counts["C"][k]["recheck"]) for k in ("repeat-1","repeat-2"))
            save(top/order/"verdict.json",{"structural_screen":qualifies,"timing":None})
        for role in "PC":
            run_archive_check(root,role,trace)
    finally:
        trace.close()


if __name__=="__main__":
    arg = argparse.ArgumentParser()
    arg.add_argument("mode",choices=("seed","mechanism"))
    arg.add_argument("root",type=Path)
    args = arg.parse_args()
    root = args.root.resolve(strict=True)
    if args.mode=="seed":
        prepare_ruff(root,OLD,NEW,identity)
        crate, = (root/"seed/registry/cache").glob("*/zlib-rs-0.5.5.crate")
        need(sha(crate)==ZLIB, "wrong locked registry archive")
    else:
        mechanism(root)
