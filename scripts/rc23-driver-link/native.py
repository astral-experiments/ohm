"""Reopen the genuine distribution, run source-native linkage and check the actual production driver."""
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g
import elf
import live
import policy
import domain
sys.path.append(str(g.PREVIOUS))
import sdk

def out(cmd,env,cwd=None):
    return subprocess.check_output(list(map(str,cmd)),env=env,cwd=cwd,text=True).strip()
def check_training(log):
    lines=log.splitlines()
    assert lines.count(g.PGO)==lines.count("patching file collector/src/compile/benchmark/mod.rs")==1
    assert any("Section `Stage 3 (BOLT) > Instrument & gather profiles` ended: OK" in line for line in lines)
    assert any("BOLT-INFO: basic block reordering modified layout" in line for line in lines)

def smoke(cargo,rustc,tmp,env):
    p=tmp/"cargo-native";p.mkdir();(p/"src").mkdir()
    (p/"Cargo.toml").write_text('[package]\nname="driver-link-smoke"\nversion="0.1.0"\nedition="2024"\n')
    (p/"src/main.rs").write_text('fn main(){println!("ordinary cargo {}",19);}\n')
    command=[cargo,"run","--offline","-q"];e=env|{"RUSTC":str(rustc),"CARGO_HOME":str(tmp/"cargo-home")}
    assert out(command,e,p)=="ordinary cargo 19"
    return {"stdout":"ordinary cargo 19","command":list(map(str,command)),"cargo":g.sha(cargo),"rustc":g.sha(rustc),"source":g.sha(p/"src/main.rs"),"binary":g.sha(p/"target/debug/driver-link-smoke")}

def main():
    w=g.checkout("build");reg,tt=g.selected();arm=os.environ["BENCH_ARM"];qa=w/"trait-evidence";src=g.read(qa/"source.json")
    assert src["role"]==arm and src["commit"]==g.text(w/"source/rust","rev-parse","HEAD")
    assert src["release_files"]==g.POLICY["release_files"];check_training((qa/"build.log").read_text(errors="replace"))
    dest=w/"trait-sdk";dest.mkdir();tmp=w/"rc23-native";tmp.mkdir()
    raw=w/"source/rust/build/dist"/(sdk.TARBASE+".tar.gz");archive=dest/"ohm.tar.gz";assert raw.is_file() and not raw.is_symlink()
    os.link(raw,archive);installed,inv=sdk.extract(archive,tmp);db=g.read(inv);component=tmp/"component-inventory.json"
    meta=g.read(component)["distribution_metadata"];assert meta["git-commit-hash"].strip()==src["commit"] and meta["rust-installer-version"].strip()=="3" and g.POLICY["tag"] in meta["version"]
    driver,=[p for p in db if re.fullmatch(r"lib/librustc_driver-[0-9a-f]+\.so",p)]
    llvm,=[p for p in db if re.fullmatch(r"lib/libLLVM\.so\.[0-9].+",p)]
    env={"PATH":"/usr/bin:/bin","HOME":str(tmp),"LC_ALL":"C","TMPDIR":str(tmp)}
    rustc=installed/"bin/rustc";rc=out([rustc,"-vV"],env);cc=out([installed/"bin/cargo","-Vv"],env);ld=out(["ldd",rustc],env)
    assert "commit-hash: "+src["commit"] in rc and "host: "+g.POLICY["target"] in rc and g.POLICY["sources"]["cargo"]["revision"] in cc
    for path in (driver,llvm):
        hit=re.search(r"(?m)^\s*"+re.escape(Path(path).name)+r"\s+=>\s+(\S+)",ld)
        assert hit and Path(hit[1]).resolve()==(installed/path).resolve()
    for f in (inv,component,qa/"source.json"):shutil.copyfile(f,dest/f.name)
    signed=w/"official-cargo/cargo";assert not signed.is_symlink() and g.sha(signed)==g.SIGNED["cargo"]["sha256"]
    csrc=g.read(w/"official-cargo/signed-cargo.json");assert csrc["cargo"]==g.SIGNED["cargo"] and csrc["archive"]==g.SIGNED["archive"]
    signed.chmod(0o755);cargo_qa=smoke(signed,rustc,tmp,env);g.save(qa/"signed-cargo.json",csrc|{"native":cargo_qa})
    subprocess.run([sys.executable,"-ISB",g.HERE/"eii/test.py",installed,qa/"eii.json",db["bin/rustc"]["sha256"],arm],env=env,check=True)
    eii=g.read(qa/"eii.json")["observed"]["integrated"]
    idir=tmp/"integrated";subprocess.run([sys.executable,"-ISB",g.HERE/"integrated/test.py",installed,idir,"ordinary" if arm=="R" else "local"],env=env,check=True)
    integrated=g.read(idir/"result.json");shutil.copyfile(idir/"result.json",qa/"integration.json")
    # The previous two programs independently establish the normal application link
    # and an explicitly opted-in compiler-driver link, including actual override calls.
    exp=qa/"driver-witness";before=w/"driver-audit-private/pre-bolt.so";image=installed/driver
    def census(img,label):
        gz=exp/(label+".json.gz");v=elf.scan(img,gz);return v,json.loads(gzip.decompress(gz.read_bytes()))
    pre,pre_rows=census(before,"pre-bolt");post,post_rows=census(image,"installed")
    assert post["sha256"]==db[driver]["sha256"]
    signed_rows=json.loads(gzip.decompress((w/"official-cargo/signed-driver.json.gz").read_bytes()))
    signed_elf=g.read(w/"official-cargo/signed-driver.json")
    assert signed_elf["sha256"]==g.SIGNED["driver"]["sha256"] and signed_elf["census_uncompressed_sha256"]==domain.rows_hash(signed_rows)
    probe_names,projection=domain.resolve(signed_rows,post_rows,rustc,tmp/"version-grammar")
    g.save(exp/"probe-domain.json",projection)
    post_with_probes=elf.scan(image,None,probe_names)
    assert {k:v for k,v in post.items() if k!="probes"}=={k:v for k,v in post_with_probes.items() if k!="probes"}
    post=post_with_probes
    pre_with_probes=elf.scan(before,None,probe_names)
    assert {k:v for k,v in pre.items() if k!="probes"}=={k:v for k,v in pre_with_probes.items() if k!="probes"}
    pre=pre_with_probes
    g.save(exp/"pre-bolt.json",pre);g.save(exp/"installed.json",post)
    policy_record,exceptions=policy.prove(w,arm,pre,post,pre_rows,post_rows)
    final_stage=Path(policy_record["pre_bolt"]["live"])
    # Dist can strip debug data after copying the stage2 driver. Verify the
    # actual executable and dynamic lookup sections across that packaging step.
    staged=elf.scan(final_stage,None)
    for k in ("linker","bolt_note","text_and_dynamic_sha256","census_uncompressed_sha256"):
        assert staged[k]==post[k],("stage2 vs installed",k)
    policy_record["packaged_stage2"]={k:staged[k] for k in ("sha256","bytes","text_and_dynamic_sha256")}
    probe=live.probe(image,post,arm,exceptions,tmp);g.save(exp/"actual-interposition.json",probe)
    policy_record["live_preload"]=probe;g.save(qa/"policy.json",policy_record)
    original_proofs={}
    for f in sorted(qa.rglob("*")):
        if f.is_file():original_proofs[str(f.relative_to(qa))]=g.sha(f)
    g.save(qa/"native-proofs.json",original_proofs)
    product={"role":arm,"source_commit":src["commit"],"source_tree":src["tree"],"archive_bytes":archive.stat().st_size,"archive_sha256":g.sha(archive),
             "source_sha256":g.sha(dest/"source.json"),"component_inventory_sha256":g.sha(component),"sdk_inventory_sha256":g.sha(inv),
             "launcher":db["bin/rustc"]|{"path":"bin/rustc"},"driver":db[driver]|{"path":driver},"llvm":db[llvm]|{"path":llvm},
             "bundled_cargo":db["bin/cargo"]|{"path":"bin/cargo"},"effective_cargo":g.SIGNED["cargo"],"signed_cargo_smoke":cargo_qa,
             "execution_pgo":g.PGO,"rustc_banner":rc,"cargo_banner":cc,"ldd":ld,"eii":eii,"integrated":integrated,
             "pre_bolt":pre,"installed_elf":post,"policy_evidence":policy_record,"qa":{k:g.sha(qa/k) for k in ("source.json","build.log","signed-cargo.json","eii.json","integration.json","policy.json","native-proofs.json")}}
    g.save(dest/"role.json",product);shutil.copyfile(dest/"role.json",qa/"role.json")
    names=("ohm.tar.gz","source.json","role.json","sdk-inventory.json","component-inventory.json")
    (dest/"SHA256SUMS").write_text("".join(g.sha(dest/n)+"  "+n+"\n" for n in names))
    for name in ("sdk-inventory.json","component-inventory.json","SHA256SUMS"):shutil.copyfile(dest/name,qa/name)
if __name__=="__main__":main()
