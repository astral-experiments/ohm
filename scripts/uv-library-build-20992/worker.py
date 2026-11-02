"""Ordinary release-build guard on the authentic, landed uv #20992 edit."""
from pathlib import Path
import json
import os
import re
import shutil
import statistics
import subprocess
from fractions import Fraction
from math import comb
import sys
import traceback
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import native
import material
import kernel
import evidence
import hardware
P=native.read(HERE/"protocol.json")
ROLES={"P":"parent","C":"candidate"}
def select(role):
    installed=native.read(native.ROOT/"sdk-locations.json")
    roots={name:Path(p).resolve(strict=True)for name,p in installed.items()}
    where=roots[role];current=native.SDK
    assert current.parent==native.V and current.name=="sdk" and where.is_dir()
    if current.exists() and current.resolve()==where:
        # Isolated one-role local openings bind the real SDK directly onto this path.
        return native.sdk_identity(role)
    assert where!=current and not current.is_symlink()
    expected=native.read(native.ROOT/"sdk-identities.json")[role]
    if not current.exists():
        current.mkdir();(current/"bin").mkdir();(current/"lib").mkdir();(current/".immutable-payloads").mkdir();shutil.copy2(where/"bin/cargo",current/"bin/cargo")
        assert native.sha(current/"bin/cargo")==expected["cargo"]
    marker=current/".checked-private-view"
    if not marker.exists() or marker.read_text()!=str(where):
        for base in (current,current/"bin",current/"lib"):
            for link in base.iterdir():
                if link.is_symlink():
                    target=Path(os.readlink(link));assert target.is_absolute() and ".."not in target.parts and any(target.is_relative_to(root)for root in roots.values())
                    link.unlink()
        for p in sorted(where.iterdir()):
            if p.name in ("bin","lib"):continue
            (current/p.name).symlink_to(p,target_is_directory=p.is_dir())
        for old in (current/"lib").glob("librustc_driver*.so"):
            assert any(old.samefile(f)for f in (current/".immutable-payloads").iterdir());old.unlink()
        driver,=(where/"lib").glob("librustc_driver*.so");payload=current/".immutable-payloads"/expected["driver"]
        if not payload.exists():shutil.copy2(driver,payload)
        assert native.sha(payload)==expected["driver"];os.link(payload,current/"lib"/driver.name)
        for p in sorted((where/"lib").iterdir()):
            if p.name!=driver.name:(current/"lib"/p.name).symlink_to(p,target_is_directory=p.is_dir())
        for p in sorted((where/"bin").iterdir()):
            if p.name in ("cargo","rustc"):continue
            (current/"bin"/p.name).symlink_to(p,target_is_directory=p.is_dir())
        launcher=current/".immutable-payloads"/("launcher-"+expected["source"])
        if not launcher.exists():shutil.copy2(where/"bin/rustc",launcher)
        assert native.sha(launcher)==native.sha(where/"bin/rustc")
        stage=current/"bin/.rustc-next";assert not stage.exists();os.link(launcher,stage)
        os.replace(stage,current/"bin/rustc");marker.write_text(str(where))
    assert native.sha(current/"bin/rustc")==native.sha(where/"bin/rustc") and native.sha(current/"bin/cargo")==expected["cargo"]
    assert not (current/"bin/rustc").is_symlink() and not (current/"bin/cargo").is_symlink()
    observed=subprocess.check_output([current/"bin/rustc","--print","sysroot"],env=native.environment(),text=True).strip()
    assert observed==str(current),(observed,str(current))
    return native.sdk_identity(role)
def reseed(seed,receipt,state,dest):
    dest.mkdir(parents=True);native.save(dest/"A-source.json",native.restore(seed,receipt))
    if state=="B":native.save(dest/"B-source.json",material.edit())
def anchors(role,hold):
    return native.ROOT/f"opening-{role}-{hold}"
def read_seed(role,hold):
    w=anchors(role,hold);s=native.TRANSIENT/f"seed-{role}-{hold}.tar.zst";j=native.read(w/"seed.json")
    return w,s,j
def verify_role_roundtrips():
    records={}
    for role in ("candidate","parent"):
        sdk=select(role);w,seed,receipt=read_seed(role,1)
        prior=[native.read(anchors(role,h)/"sdk.json")for h in (1,2)]
        assert all(k["launcher_file"]==sdk["launcher_file"] and k["cargo_file"]==sdk["cargo_file"] for k in prior)
        dest=native.ROOT/("preclock-return-"+role);reseed(seed,receipt,"A",dest)
        observed=kernel.enroll(dest/"process","A")
        roster=kernel.match(native.read(w/"A-kernel/process/observed-rustcs.json"),observed)
        anchor=native.read(w/"anchor-A/native-products.json");actual=evidence.capture(dest,anchor)
        native.save(dest/"all-products.json",evidence.compare(anchor,actual,"A"))
        linked=native.witness(dest,role,"A",sdk["driver"])
        assert linked["execute"]["stdout"]==native.read(w/"anchor-A/linked.json")["execute"]["stdout"]
        records[role]=dict(kernel=roster,rustc_queries=observed["other_rustc_queries"],launcher=sdk["launcher_file"],cargo=sdk["cargo_file"],all_products=native.sha(dest/"all-products.json"),behavior=native.sha(dest/"linked.json"))
    native.save(native.ROOT/"preclock-role-returns.json",records)
    return records
def open_from_seed(role,hold,seed,receipt,where,driver):
    for state in ("A","B"):
        anchor=where/("anchor-"+state);reseed(seed,receipt,state,anchor)
        if state=="B":native.ordinary(anchor/"pure-cargo")
        reference=evidence.capture(anchor);link=native.witness(anchor,role,state,driver)
        native.save(anchor/"native-metadata.json",{n:evidence.wire.ident(evidence.meta.native_header(evidence.meta.metadata_member(evidence.unpack(v))[1]))for n,v in reference["archives"].items()})
        native.save(anchor/"hostile-native-mutants.json",evidence.hostile(reference))
        for vv in (False,True):
            arm=where/(state+("-verbose"if vv else "-kernel"));reseed(seed,receipt,state,arm)
            k=kernel.enroll(arm/"process",state,vv)
            actual=evidence.capture(arm,reference);native.save(arm/"all-equivalent.json",evidence.compare(reference,actual,state))
            if vv:
                true=native.read(where/(state+"-kernel")/"process/observed-rustcs.json")
                native.save(arm/"argv-match.json",kernel.match(true,k))
        if state=="B":
            baseline=native.read(where/"anchor-A/linked.json");transition=native.linked.compare(baseline,link);assert transition
            native.save(where/"A-B-behavior.json",transition)
    return where
def enrollment():
    hardware.enter();bank=native.TRANSIENT/"registry";assert native.read(native.ROOT/"registry.json")["count"]==658
    donor=Path(os.environ["GITHUB_WORKSPACE"])/"uv-donor"
    base_shapes={}
    for hold,order in enumerate((("parent","candidate"),("candidate","parent")),start=1):
        for role in order:
            hardware.caller_watchdog();info=select(role);where,seed,_,_=native.open_seed(role,hold,donor,bank)
            open_from_seed(role,hold,seed,native.read(where/"seed.json"),where,info["driver"])
            for state in ("A","B"):
                k=native.read(where/(state+"-kernel")/"process/observed-rustcs.json")
                if state not in base_shapes:base_shapes[state]=k
                else:native.save(where/(state+"-cross-kernel-shape.json"),kernel.match(base_shapes[state],k))
                if hold==2:
                    left=native.read(anchors(role,1)/("anchor-"+state)/"native-products.json")
                    right=native.read(where/("anchor-"+state)/"native-products.json")
                    native.save(where/(state+"-across-independent.json"),evidence.compare(left,right,state,independent=True))
            native.save(where/"opening.json",dict(hold=hold,role=role,A_B=native.sha(where/"A-B-behavior.json"),seed=native.sha(where/"seed.json"),A=native.sha(where/"anchor-A/native-products.json"),B=native.sha(where/"anchor-B/native-products.json"),actual_A=native.sha(where/"A-kernel/process/observed-rustcs.json"),actual_B=native.sha(where/"B-kernel/process/observed-rustcs.json")))
    sealed={}
    cargo_receipts=[]
    for h in (1,2):
        for r in ("parent","candidate"):
            w=anchors(r,h);sealed[f"{r}-{h}"]={p.relative_to(w).as_posix():native.sha(p) for p in sorted(w.rglob("*.json"))}
            sdk=native.read(w/"sdk.json");cargo_receipts.append((tuple(sdk["cargo_file"]),sdk["canonical_cargo"],sdk["canonical_sysroot"]))
    assert len(set(cargo_receipts))==1
    verify_role_roundtrips()
    native.save(native.ROOT/"all-four-openings.json",sealed)
def verify_openings():
    record=native.read(native.ROOT/"all-four-openings.json")
    assert len(record)==4
    for tag,files in record.items():
        assert all(native.sha(native.ROOT/("opening-"+tag)/n)==h for n,h in files.items())
def one(number,arm,hold,role,mode):
    info=select(role);w,s,j=read_seed(role,hold);out=native.ROOT/f"pair-{number:02d}"/f"{arm}-{role}"/mode
    reseed(s,j,"B",out);anchor=native.read(w/"anchor-B/native-products.json")
    selector=native.read(w/"B-kernel/process/observed-rustcs.json")
    if mode=="ordinary":
        measured=native.ordinary(out/"native")
        assert measured["argv"]==kernel.command();linked=native.witness(out,role,"B",info["driver"])
        assert native.linked.compare(native.read(w/"anchor-A/linked.json"),linked)
    elif mode=="whole-instructions":measured=hardware.inherited(out/"native")
    elif mode=="rustcs":measured=hardware.per_compiler(out/"native",selector)
    else:raise ValueError(mode)
    retained=evidence.capture(out,anchor)
    proof=evidence.compare(anchor,retained,"B");native.save(out/"all-outputs.json",proof)
    if mode=="ordinary":
        text=(out/"native/stderr").read_text();finished=re.findall(r"Finished .*? in ([0-9.]+)s",text)
        assert len(finished)==1 and float(finished[0])>0;measured=dict(measured,cargo_finished_seconds=float(finished[0]))
    rec=dict(number=number,position=arm,hold=hold,role=role,mode=mode,source=info["source"],sample=measured,seed=native.sha(w/"seed.json"),outputs=native.sha(out/"native-products.json"),observed=native.sha(out/"all-outputs.json"))
    native.save(out/"accepted.json",rec);return rec
def measure():
    import verify_returns
    hardware.enter();verify_openings();verify_returns.reopen();samples=[]
    for hold,orders in enumerate(P["orders"],start=1):
        for ix,labels in enumerate(orders,start=1):
            number=(hold-1)*4+ix
            # Both underlying wall clocks form a pair before opening separate PMU visits.
            for mode in ("ordinary","whole-instructions","rustcs"):
                for pos,label in enumerate(labels,start=1):
                    hardware.caller_watchdog();samples.append(one(number,pos,hold,ROLES[label],mode))
    hardware.clock_control("clock-post")
    rows={}
    for r in samples:
        key=r["number"];bucket=rows.setdefault(key,{})
        bucket.setdefault(r["role"],{})[r["mode"]]=r
    assert len(samples)==48 and len(rows)==8
    summary=wall_rule(rows)
    native.save(native.ROOT/"result.json",dict(registration=native.sha(HERE/"protocol.json"),all_four=native.sha(native.ROOT/"all-four-openings.json"),clock_pre=native.sha(native.ROOT/"clock-pre/passed.json"),clock_post=native.sha(native.ROOT/"clock-post/passed.json"),rows=rows,**summary))
def wall_rule(rows):
    assert set(rows)==set(range(1,9))
    ratios=[]
    for number,v in sorted(rows.items()):
        assert set(v)=={"parent","candidate"}and all(set(x)=={"ordinary","whole-instructions","rustcs"}for x in v.values())
        ratios.append(Fraction(v["candidate"]["ordinary"]["sample"]["wall_ns"],v["parent"]["ordinary"]["sample"]["wall_ns"]))
    medians=[statistics.median(ratios[i:i+4])for i in (0,4)]
    k=sum(v<Fraction(11,10)for v in ratios);p=sum(comb(8,i) for i in range(k,9))/256
    return dict(candidate_over_parent=list(map(float,ratios)),hold_medians=list(map(float,medians)),strictly_below_1p10=k,sign_one_sided=p,admitted=all(v<Fraction(21,20)for v in medians) and k>=7)
def main():
    try:
        {"calibrate":hardware.calibrate,"enroll":enrollment,"measure":measure}[sys.argv[1]]()
    except BaseException:
        native.ROOT.mkdir(exist_ok=True,parents=True)
        (native.ROOT/("refusal-"+sys.argv[1]+".txt")).write_text(traceback.format_exc());raise
if __name__=="__main__":main()

