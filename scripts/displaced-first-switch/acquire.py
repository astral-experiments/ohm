"""One uninstrumented ordinary K CLI switch. All diagnostic table work happens after Cargo exits."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tables as t
import mount_evidence as m

HIST = "ae9ed53266a0106f19571e692a05fb65d28f06b2"
SOURCE = "caef389ed580829583f1a63df129b7b649e43508"
MANIFEST = "c29e2e57626491804d9c24e5fa50a709015a002067a3bf39e884d8b6ef0fea43"
DRIVER = "72f0f62adf9c301a87c2db3427b097bab60bfb3857caa84123489f69d339f9fa"
REF = "refs/heads/charlie/qa-branch-displaced-tables-20261031"

def build_codec(b, arm):
    out = b.OUT / "codec"
    out.mkdir()
    root = b.ROOT / "isolated-codec"
    root.mkdir()
    source = root / "source"
    shutil.copytree(HERE / "codec", source)
    expected = json.loads((source / "source.json").read_bytes())
    t.need(expected["K_compiler_tree"] == b.COMPARE["K"] and t.sha(source/"src/pack_stream.rs")==expected["verbatim_pack_stream_sha256"], "foreign codec")
    env = arm.copy()
    env.pop("CARGO_ENCODED_RUSTFLAGS")
    env.update(CARGO_HOME=str(root/"cargo-home"), CARGO_TARGET_DIR=str(root/"target"), CARGO_BUILD_BUILD_DIR=str(root/"build"))
    commands = []
    for key, args in (("fetch",["fetch","--locked"]),("features",["tree","--locked","--offline","-e","features"]),("build",["build","--release","--locked","--offline"])):
        argv = ["cargo","+ohm",*args]
        actual = env | ({"CARGO_NET_OFFLINE":"false"} if key=="fetch" else {})
        rp=subprocess.run(argv,cwd=source,env=actual,capture_output=True,timeout=300)
        for channel in ("stdout","stderr"):
            (out/(key+"."+channel)).write_bytes(getattr(rp,channel))
        t.need(rp.returncode==0,("codec "+key,rp.returncode,rp.stderr[-400:]))
        commands.append({"argv":argv,"exit":rp.returncode,"env":actual})
    crates = {p.name:t.sha(p) for p in (root/"cargo-home/registry/cache").glob("*/*.crate")}
    t.need(crates=={n+"-"+v+".crate":h for n,(v,h) in expected["crates"].items()},"not the compiler's six locked codec crates")
    exe = root/"target/release/displaced-table-codec-qa"
    shutil.copy2(exe,out/"reference-encoder")
    t.save(out/"build.json",dict(commands=commands,registry=crates,executable_sha256=t.sha(exe),source=expected))
    return exe

def copy_file(src,dest,want):
    dest.parent.mkdir(parents=True,exist_ok=True)
    h=hashlib.sha256();n=0
    with dest.open("xb") as f:
        while data:=src.read(1<<20):
            h.update(data);n+=len(data);f.write(data)
    t.need(h.hexdigest()==want[0] and n==want[1],("retained stream differs",dest))
    return [n,want[0]]

def materialize(work, shadow, first, records, output):
    """Copy shareable witnesses only after the double-write and original-root checks."""
    output.mkdir();manifest={}
    for unit,owner in records.items():
        for k,row in owner["streams"].items():
            stem=Path(unit).name+"/"+k
            for state,source in (("A",row["packed"]),("B",row["native_B"])):
                key=state+"/"+stem+".zlib"
                if state=="A":
                    with (shadow/row["shadow"]).open("rb") as f:
                        manifest[key]=copy_file(f, output/key, [source['sha256'],source['bytes']])
                else:
                    rel=source['path']
                    with t.regular(work,rel,first[rel]) as f:
                        manifest[key]=copy_file(f, output/key, [source['actual_sha256'],source['bytes']])
    t.need(len(manifest)==80 and sum(x[0] for x in manifest.values())<1600*2**20,"unbounded evidence payload")
    t.save(output/"streams.json",manifest)
    return manifest

def main(history,source):
    sys.path.insert(0,str(history/"scripts/branch-return-pmu"))
    import worker as w
    b=w.b;root=b.WORK;out=b.OUT
    b.prepare_checkout(history,HIST,"scripts");b.prepare_checkout(source,SOURCE,"scripts/branch-return-source")
    expected=json.loads((w.HERE/"historical-sources.json").read_bytes())
    t.need(expected['git']=="99dd1ed50dc39354707148ed77ec2ec5d8235978" and all(t.sha(history/name)==h for name,h in expected['files'].items()),"wrong ordinary CLI and product oracle")
    t.need(os.environ["GITHUB_REF"]==REF and os.environ["GITHUB_REPOSITORY"]==b.REPO and os.environ["GITHUB_RUN_ATTEMPT"]=="1" and b.git(HERE,"rev-parse","HEAD")==os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"], "not the reviewed private QA dispatch")
    t.need(b.spec()["manifest"]==MANIFEST and b.spec()["head"]==SOURCE and b.spec()["run"]==41199659076, "different physical source kit")
    t.need(root.resolve()==root and (root/".owned-by-packed-study").read_text()==str(b.ROOT) and shutil.disk_usage(root).free>=10*2**30 and shutil.disk_usage(out).free>=32*2**30,"missing sentinel or native storage reserve")
    mode=(out/"storage-mode.txt").read_text().strip()
    mount,=json.loads((out/"filesystem.json").read_bytes())["filesystems"]
    dev=root.stat().st_dev
    t.need(mount["maj:min"]==f"{os.major(dev)}:{os.minor(dev)}" and root.is_relative_to(Path(mount["target"])) and mount["source"] and mount["fstype"], ("inconsistent source mount",mount))
    t.need((mode=="private-ext4" and mount["fstype"]=="ext4" and root.is_mount()) or (mode=="runner-filesystem" and not root.is_mount()),("unqualified file system",mode,mount))
    t.save(out/"backend.json",dict(mode=mode,device=dev,mount=mount,free_at_start=shutil.disk_usage(root).free,block_size=os.statvfs(root).f_frsize))
    t.save(out/"enrollment.json",dict(head=os.environ["GITHUB_SHA"],run=int(os.environ["GITHUB_RUN_ID"]),attempt=1,job=os.environ["GITHUB_JOB"],runner=os.environ["RUNNER_NAME"],boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),source=b.spec(),history=HIST,plan=t.sha(HERE/"PLAN.md"),cargo=w.CARGO))
    reg=b.acquire(source)
    (out/"initial").mkdir()
    env=b.activate("Kon",reg,out/"initial")
    arm=json.loads((out/"initial/arm.json").read_bytes())
    t.need(any(k.startswith("lib/librustc_driver-") and v[0]==DRIVER for k,v in arm["files"].items()) and env["CARGO_ENCODED_RUSTFLAGS"]=="-Zohm-branch-cache=yes","different K driver or ordinary profile")
    b.fresh_outputs();b.prepare_inputs(w.kit,env);w.historical.calibration()
    codec=build_codec(b,env);refs={}
    b.fresh_outputs()
    clean=w.receipt("Kon","cold-B","B","clean",env,out/"empty-B",refs)
    b.fresh_outputs()
    initial=w.receipt("Kon","cold-A","A","clean",env,out/"cold-A",refs)
    initial_ledger=t.load(out/"cold-A")
    displaced=t.cold(root,initial_ledger)
    t.save(out/"pre-switch-cold-source.json",displaced)
    switched=w.receipt("Kon","first-B","B","ordinary",env,out/"first-B",refs)
    t.need(initial["dirty"]==clean["dirty"]==375 and switched["dirty"]==20 and clean["cli"]==switched["cli"]!=initial["cli"] and switched["reader"]==clean["reader"],"375/20 names and independent clean native files")
    ledger=t.load(out/"first-B")
    scratch=root/"diagnostic-temporary";shadow=root/"displaced-shadow"
    stages=out/"per-crate";stages.mkdir()
    def progress(index,unit,row):
        t.save(stages/(f"{index:02d}-"+Path(unit).name+".json"),{unit:row})
        t.need(shutil.disk_usage(root).free>2*2**30,"private workload reserve")
    records=t.observe(root,initial_ledger,ledger,displaced,shadow,scratch,codec,progress)
    # Capture the actual coexisting files before introducing a portable copy outside these roots.
    # Escrow every available stream even if the final mount/ownership or allocation check refuses.
    t.save(out/"tables.json",records)
    try:
        shadow_rows={str(p.relative_to(shadow)):t.shape(p.lstat()) for p in (shadow,*sorted(shadow.rglob("*")))}
        w.publish(out/"shadow-inodes.json.gz",shadow_rows)
        du=subprocess.check_output(["/usr/bin/du","-sB1","--total","--",root/"target",root/"build",shadow],text=True)
        (out/"coexistence-du.txt").write_text(du)
        scanned=subprocess.check_output(["/usr/bin/find",shadow,"-printf","%D %i %b\\n"])
        (out/"shadow-find.txt").write_bytes(scanned)
        fdinfo=m.capture(root,shadow,ledger)
        w.publish(out/"mount-inodes.json.gz",fdinfo)
    finally:
        streams=materialize(root,shadow,ledger,records,b.ROOT/"table-streams")
    (out/"post-shadow").mkdir()
    post=w.disk.allocated(root/"target",root/"build",out/"post-shadow")
    t.need(t.load(out/"post-shadow")==ledger and post["allocated"]==switched['allocated'], "diagnostic altered a native product, name, link or allocation")
    t.need(du.splitlines()[-1].split()==[str(post['allocated']+t.allocated_tree(shadow)),"total"],"independent GNU du measure of all staged bytes disagrees")
    t.need(not list(scratch.iterdir()), "native-B codec calibration files leaked")
    admitted=m.validate(fdinfo,ledger,shadow_rows)
    independent={tuple(map(int,l.split()[:2])):int(l.split()[2])*512 for l in scanned.splitlines()}
    t.need(independent=={tuple(q[:2]):q[4]*512 for q in shadow_rows.values()} and len(independent)==len(shadow_rows)==61,"shadow allocation aliases")
    t.save(out/"mount-admission.json",admitted)
    t.need(t.sha(b.SDK/"bin/cargo")==b.CARGO_ELF and t.sha(b.SDK/b.WILD)==b.WILD_ELF and b.inventory(b.SDK)==reg["K"] and not w.kit.git("status","--porcelain"),"changed SDK or Ruff")
    t.save(out/"complete.json",dict(cold=initial,empty=clean,first=switched,source_table_count=40,native_B_calibrations=40,du_coexistence=du,shadow_allocated=t.allocated_tree(shadow),stream_index_sha256=t.sha(b.ROOT/"table-streams/streams.json"),stream_bytes=sum(v[0] for v in streams.values()),post_original=post["allocated"],qualified=True))
    print("qualified storage-only acquisition",flush=True)

if __name__=="__main__":
    try: main(*map(Path,sys.argv[1:]))
    except BaseException:
        dst=Path(os.environ['RUNNER_TEMP'])/"ohm-branch-object-qa/logs"
        if dst.is_dir(): (dst/"failure.txt").write_text(traceback.format_exc())
        raise
