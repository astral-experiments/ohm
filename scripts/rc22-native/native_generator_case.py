"""Compare warm native-backed generator diagnostics with independent clean checks."""
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import common
import fixture

def exercise(out, sdk, role):
    base=out/"native-generator"/role
    base.mkdir(parents=True)
    reports=out/"reports"/role/"native"
    reports.mkdir(parents=True)
    native=base/"native"
    bodies=fixture.providers(native,reports)
    src=base/"project"
    fixture.project(src,"zmij",common.seed("ruff")/"Cargo.lock")
    manifest=src/"Cargo.toml"
    manifest.write_text(manifest.read_text().replace("[dependencies]","[build-dependencies]"))
    (src/"src/main.rs").unlink()
    (src/"src/lib.rs").write_text('include!(concat!(env!("OUT_DIR"),"/generated.rs"));\npub fn consumer() { generated(); }\n')
    (src/"build.rs").write_text('''#[link(name="rc22_native_choice",kind="static",modifiers="-bundle")]
unsafe extern "C" { fn qa_rc22_value() -> i32; }
fn main() {
    assert_eq!(zmij::Buffer::new().format(1.25_f64), "1.25");
    let value = unsafe { qa_rc22_value() };
    let dir = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    std::fs::write(dir.join("generated.rs"), format!("#[deprecated(note=\\"rc22 native value {value}\\")] pub fn generated() {{}}\\n")).unwrap();
    println!("cargo:rerun-if-changed=build.rs");
}
''')
    common.save(reports/"sources.json",{name:common.sha(src/name) for name in ("Cargo.toml","Cargo.lock","src/lib.rs","build.rs")})
    def environment(label):
        work=base/label;work.mkdir()
        env=common.context(work,sdk)
        env["CARGO_ENCODED_RUSTFLAGS"]="\x1f".join(arg for loc in ("early","late") for arg in ("-L","native="+str(native/loc)))
        subprocess.run(["cargo","+ohm","fetch","--locked","--target",common.GNU],cwd=src,env=env,check=True,stdout=subprocess.DEVNULL)
        return env
    warm=environment("warm")
    cmd=["cargo","+ohm","check","--lib","--locked","--offline","--message-format=json"]
    results=[]
    for i,(step,state,want) in enumerate([("initial","low",17),("unchanged","low",17),("appearance","high29",29),("same-stat","high41",41),("malformed","bad",None),("repair","high29",29),("missing","absent",None),("restored","low",17)]):
        transition=fixture.configure(native,bodies,state)
        matched={}
        for level,env in (("warm",warm),("empty",environment("empty-"+step))):
            run=subprocess.run(cmd,cwd=src,env=env,capture_output=True)
            name=step+"-"+level
            for key,b in (("stdout",run.stdout),("stderr",run.stderr)):
                (reports/(name+"."+key+".gz")).write_bytes(gzip.compress(b,mtime=0))
            records=[json.loads(line) for line in run.stdout.splitlines() if line.startswith(b"{")]
            common.require(records and records[-1].get("reason")=="build-finished",name+" missing Cargo terminal row")
            messages=[v["message"] for v in records if v["reason"]=="compiler-message"]
            values={int(n) for msg in messages for n in re.findall(r"rc22 native value (\d+)",msg.get("message",""))}
            visible=run.stderr.decode(errors="replace")+"\n"+"\n".join(str(msg.get("rendered","")) for msg in messages)
            observations=dict(code=run.returncode,values=sorted(values),finished=records[-1]["success"],native_diagnostic=fixture.LIB in visible)
            common.save(reports/(name+".json"),observations);matched[level]=observations
        results.append(dict(step=step,transition=transition,observed=matched));common.save(reports/(step+"-comparisons.json"),results[-1])
        for v in matched.values():
            good=(v["code"]==0 and v["finished"] and v["values"]==[want]) if want is not None else (v["code"]!=0 and not v["finished"] and v["native_diagnostic"])
            common.require(good,{"case":step,"role":role,"expected":want,"actual":v})
    common.save(reports/"complete.json",dict(comparisons=results,job=common.job()))
