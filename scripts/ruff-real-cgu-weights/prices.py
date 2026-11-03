"""Replay one physically restored warm Cargo checkpoint under rustc's instruction profiler."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent/"ruff-source-placement")]
import common
import object_windows
import archive_diagnostic as archives
import worker as prior

BRANCH = "charlie/qa-real-cgu-weights-20261102"
DIGEST = lambda b: hashlib.sha256(b).hexdigest()
EXPECTED = json.loads((HERE/"owners.json").read_bytes())


def save(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True, indent=1)+"\n")


def checkpoint(root, names):
    """Bind contents, mtimes and hardlink groups across the entire Cargo state."""
    h=hashlib.sha256()
    first={}
    counts={"entries":0,"regular":0,"hardlinks":0}
    for name in sorted(names):
        tree=root/name
        for path in [tree,*sorted(tree.rglob("*"))]:
            s=path.lstat()
            rel=str(path.relative_to(root))
            key=(s.st_dev,s.st_ino)
            content=None
            if stat.S_ISREG(s.st_mode):
                counts["regular"]+=1
                if key in first:
                    counts["hardlinks"]+=1
                    content=["link",first[key]]
                else:
                    first[key]=rel
                    with path.open("rb") as f:
                        content=["bytes",s.st_size,hashlib.file_digest(f,"sha256").hexdigest()]
            elif stat.S_ISLNK(s.st_mode):
                content=["symlink",os.readlink(path)]
            else:
                assert stat.S_ISDIR(s.st_mode),rel
            h.update(json.dumps([rel,s.st_mode,s.st_mtime_ns,content],separators=(",",":")).encode()+b"\n")
            counts["entries"]+=1
    return {"sha256":h.hexdigest(),**counts}


def elf_members(path, expected):
    buf = path.read_bytes()
    assert buf.startswith(b"!<arch>\n")
    offset = 8
    long_names = b""
    members = {}
    while offset < len(buf):
        header = buf[offset:offset+60]
        assert header[58:60] == b"`\n"
        size = int(header[48:58].strip())
        name = header[:16].rstrip()
        data = memoryview(buf)[offset+60:offset+60+size]
        assert len(data) == size
        offset += 60 + size + (size & 1)
        if name == b"//":
            long_names = bytes(data)
            continue
        if name.startswith(b"/") and name[1:].isdigit():
            at = int(name[1:])
            name = long_names[at:long_names.index(b"/\n", at)]
        if name.startswith(b"#1/"):
            n = int(name[3:])
            name, data = bytes(data[:n]).rstrip(b"\0"), data[n:]
        if name.rstrip(b"/").endswith(b".o"):
            units = [u for u in expected if u.encode() in name]
            assert len(units)==1 and units[0] not in members and data[:4]==b"\x7fELF", name
            members[units[0]] = DIGEST(data)
    assert offset==len(buf) and members==expected, ("different or missing genuine objects", len(members), [(k,v,members.get(k)) for k,v in expected.items() if v!=members.get(k)][:3])
    return members


def history(kit, where, work, repo, env, which, suite, graph, cmd, extras, gold, score, opens, admit, *, normal, bare, out):
    args=[kit,where,work,repo,env,which,suite,graph,cmd,extras,gold,score,opens,admit]
    if not (kit.active=="P" and suite=="option" and which=="new" and where.parent.name=="P-edit"):
        return normal(*args)
    assert not score and opens and admit and "RUSTC_WRAPPER" not in env
    assert work.name=="work" and work.resolve().is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve())
    snap=out.parent/"cgu-profile-private-state";snap.mkdir()
    dirs=("build","target","cargo-home")
    for label in ("old","ordinary","repeat","profiled"):
        (snap/label).mkdir()
    before=checkpoint(work,dirs)
    subprocess.run(["cp","-a","--reflink=auto",*[work/name for name in dirs],snap/"old"],check=True)
    assert checkpoint(snap/"old",dirs)==before, "copied state differs in bytes, mtimes or hardlinks"
    baseline=normal(*args)
    rows=prior.replay.cargo_rows((where/"outer.stdout").read_bytes())
    archive=prior.study.artifact(prior.study.results(rows,True),prior.study.OWNER)
    initial=archives.capture(out,"ordinary",archive)
    assert (initial["sha256"],initial["bytes"])==(baseline["owner_archive"]["sha256"],baseline["owner_archive"]["bytes"])
    reference=elf_members(archive,EXPECTED["all_native"])
    save(out/"normal.json",{"argv":baseline["root_argv"],"roster":baseline["raw_roster"],"members":reference,"elf":baseline["elf"],"verdict":baseline["verdict"]})

    for name in dirs:
        (work/name).rename(snap/"ordinary"/name)
    try:
        # Leaves the pristine checkpoint and the first ordinary result intact for the third history.
        footprint=int(subprocess.check_output(["du","--apparent-size","-sb",snap/"old"]).split()[0])
        prior.guards.admit(prior.guards.resources(work,out))
        assert shutil.disk_usage(work).free-footprint > 15<<30, "additional independent plain replay exceeds the disk reserve"
        subprocess.run(["cp","-a","--reflink=auto",*[snap/"old"/n for n in dirs],work],check=True)
        assert checkpoint(work,dirs)==before, "ordinary repeat did not start from the same original checkpoint"
        repeat_args=args.copy()
        repeat_args[1]=where.parent/"new-plain-repeat"
        second=normal(*repeat_args)
        second_rows=prior.replay.cargo_rows((repeat_args[1]/"outer.stdout").read_bytes())
        second_archive=prior.study.artifact(prior.study.results(second_rows,True),prior.study.OWNER)
        second_layout=archives.capture(out,"ordinary-repeat",second_archive)
        assert (second_layout["sha256"],second_layout["bytes"]) == (second["owner_archive"]["sha256"],second["owner_archive"]["bytes"])
        assert elf_members(second_archive,EXPECTED["all_native"])==reference
        first_cmd,repeated_cmd=[json.loads((loc/"command.json").read_bytes()) for loc in (where,repeat_args[1])]
        assert all(first_cmd[k]==repeated_cmd[k] for k in ("ordinary","environment"))
        first_exec,second_exec=[object_windows.ordinary_execs(loc/"trace",prior.support.EXEC) for loc in (where,repeat_args[1])]
        assert object_windows.Counter(first_exec)==object_windows.Counter(second_exec)
        gates=("root_argv","raw_roster","elf","verdict","inventory","dirty")
        save(out/"archive-plain-witness.json",{"first":{k:baseline[k] for k in (*gates,"owner_archive")},
             "repeat":{k:second[k] for k in (*gates,"owner_archive")},"complete_ordinary_execs":len(first_exec),
             "environment_sha256":DIGEST(json.dumps(first_cmd["environment"],sort_keys=True).encode()),"checkpoint":before,
             "source":EXPECTED["source"],"parent":"531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5",
             "boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"run":os.environ["GITHUB_RUN_ID"],
             "sha":os.environ["GITHUB_SHA"]})
        assert all(second[k]==baseline[k] for k in gates), "plain repeat changed the ordinary command or consumer"
        for name in dirs:
            (work/name).rename(snap/"repeat"/name)
            (snap/"old"/name).rename(work/name)
        shutil.rmtree(snap/"repeat")
        assert checkpoint(work,dirs)==before, "observed command did not start from the same original checkpoint"
        save(out/"checkpoint.json",before)
        loc=where.parent/"new-profiled"
        object_windows.observe(prior,kit,loc,work,repo,env,cmd,suite,graph,which,extras,gold,baseline,reference,out,EXPECTED,elf_members,save)
        assert all(p["whole_bytes_equal"] for p in archives.compare(out)["pairs"].values()), "original/repeated/observed rlibs differ"
    except Exception as error:
        save(out/"refusal.json",{"error":str(error)[:4000],"phase":"restored ordinary Cargo edit"})
        for which in ("outer.stderr","outer.stdout"):
            log=where.parent/"new-profiled"/which
            if log.is_file():
                (out/("refused-"+which+".gz")).write_bytes(gzip.compress(log.read_bytes(),6,mtime=0))
        raise
    finally:
        for name in dirs:
            if (work/name).exists():
                (work/name).rename(snap/"profiled"/name)
            (snap/"ordinary"/name).rename(work/name)
        shutil.rmtree(snap)
    raise archives.DiscoveryComplete()


def main():
    assert os.environ["GITHUB_REF"]=="refs/heads/"+BRANCH and os.environ["GITHUB_RUN_ATTEMPT"]=="1"
    assert subprocess.check_output(["git","-C",HERE,"rev-parse","HEAD"]).decode().strip()==os.environ["REVIEWED_HEAD"]==os.environ["GITHUB_SHA"]
    assert os.environ["PLACEMENT_FACTORY"]=="41475100027"
    out=Path(os.environ["RUNNER_TEMP"])/"cgu-profile-report";out.mkdir()
    object_windows.prepare(out,save)
    original_suite=prior.acquire.suite_run
    bare=prior.acquire.phase
    def suite(*args):
        normal=prior.acquire.phase
        def wrap(*visit):
            return history(*visit,normal=normal,bare=bare,out=out)
        with patch.object(prior.acquire,"phase",wrap):
            return original_suite(*args)
    try:
        with patch.object(prior.transport,"BRANCH",BRANCH),patch.object(prior.acquire,"suite_run",suite):
            prior.collect("admit",1,{"option":Path(sys.argv[1]).resolve(strict=True)})
    except archives.DiscoveryComplete:
        save(out/"archive-only-terminal.json",{"all_three_complete_rlibs_equal":True,"real_unit_prices_opened":False})
        return
    raise RuntimeError("the enrolled real P archive diagnostic did not execute")

if __name__=="__main__":
    # This run has its own head. The downloaded factory remains on its original branch.
    with patch.object(common, "BRANCH", BRANCH):
        assert common.git(common.HERE, "rev-parse", "HEAD:scripts/ruff-source-placement") == "0cc1467837102b563b445be2193cd155006517a2"
        if len(sys.argv) == 3 and sys.argv[1] == "receive":
            prior.receiver.install(Path(sys.argv[2]), registration=common.enrollment())
        else:
            main()
