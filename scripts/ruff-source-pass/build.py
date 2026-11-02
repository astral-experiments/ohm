"""Build just the two complete register-coalescer translation units against signed Ohm -22."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
LLVM = "1b9c0d5ff9bbe7634aead059efe6b11a7eeba145"
TREE = "9a6c21823a2dd558efa938c1074aa28e352bc92d"
RUST = "fba1b05a7bd8bdc73080edd02f672cef44648267"
DEV = "5101e197006f166da80747b6cbb5bc05f40fdf9ac8226dd90ce8797173bbea1f"
LIB = "libLLVM.so.23.1-rust-1.99.0-beta"
SIGNED = "43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51"
PATCH = "8df654501c995c2e419a6402c15bed1942df7e423df982448ab0d22cffee051b"
OVERLAY = "2c438a14544e426cc1f254aa37a918ddbd784d3c333cc484f6aad7c579cc8f66"
QUALIFIED_PLAIN = {"stock":"692e59901cc2b9f00d4e04d0941df562b159f6d701490855060feda7d6d50947",
                   "candidate":"074561b2cfaa3b623081b3ce2c701bee34cb40f4d334c1c310b21bf1a19ddf99"}
OPTIONS = ("join-liveintervals","terminal-rule","join-splitedges","join-globalcopies","verify-coalescing",
           "late-remat-update-threshold","large-interval-size-threshold","large-interval-freq-threshold")
# Exact output of this Rust-CI distribution's llvm-config --cxxflags, except its include directory.
ABI = ["-std=c++17", "-D_GNU_SOURCE", "-D_GLIBCXX_USE_CXX11_ABI=1", "-D__STDC_CONSTANT_MACROS",
       "-D__STDC_FORMAT_MACROS", "-D__STDC_LIMIT_MACROS", "-fno-exceptions", "-fno-rtti"]
FILES = {"llvm/lib/CodeGen/RegisterCoalescer.cpp":("fa1616e57bb19d4096920a3518db0c0da21d735b","426715cf2ea5bf705ec793a88d7e5c415e25025152437b3d7fa9b0381bfa17c1"),
         "llvm/lib/CodeGen/RegisterCoalescer.h":("c4aa6276c61b74016078a857025c9733067722c6","4e3f176f2e4f6ec785dfeb937219e98cf404298e95a676c89571243d15a5b82b"),
         "llvm/include/llvm/CodeGen/LiveIntervals.h":("99a0122265d3bfd4617c6b358b283579fa6665fb","c82854bd5558f2608c0c32b60fad0a5e9d11f7daf573d75b34e38957ff6f1907")}


def need(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    import hashlib
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(args, cwd, env=None):
    return subprocess.check_output([str(a) for a in args], cwd=cwd, env=env, text=True, timeout=240).strip()


def replace(text, old, new):
    need(text.count(old) == 1, ("unexpected upstream structure", old))
    return text.replace(old, new)


def derive(source, arm, inspected):
    for option in OPTIONS:
        source = replace(source, '"'+option+'"', '"ohm-native-'+option+'"')
    source = replace(source, "char &llvm::RegisterCoalescerID = RegisterCoalescerLegacy::ID;", "")
    start = source.index("INITIALIZE_PASS_BEGIN(RegisterCoalescerLegacy,")
    end = source.index("[[nodiscard]] static bool isMoveInstr(", start)
    source = source[:start] + (HERE/"pipeline.inc").read_text() + source[end:]
    preamble = (HERE/"preamble.inc").read_text()
    if inspected:
        preamble += (HERE/"inspect.inc").read_text()
        marker = "bool RegisterCoalescer::run(MachineFunction &fn) {"
        source = replace(source, marker, marker+"\n  OhmMachines.fetch_add(1, std::memory_order_relaxed);")
        line = ("    bool Split = shrinkToUses(&SrcInt, &DeadDefs, SegmentsUnchanged);" if arm == "candidate"
                else "    shrinkToUses(&SrcInt, &DeadDefs);")
        count = "    OhmDirect.fetch_add(1, std::memory_order_relaxed);\n"
        if arm == "candidate":
            count += "    if (SegmentsUnchanged) OhmSkips.fetch_add(1, std::memory_order_relaxed);\n"
        source = replace(source, line, count + line)
    return preamble.replace("@ARM@", arm) + source


def headers(src, out):
    ledger = json.loads((HERE/"headers.json").read_bytes())
    need(len(ledger) == 239 and sha(HERE/"headers.json") == "6bce89009f3e85bfb009c8ee3874b6b04cf41820bb09ee0808723fdffa581b73"
         and sha(HERE/"rust-ci-generated-headers.tar.gz") == OVERLAY, "Rust CI header closure")
    generated = {key for key, (_, blob) in ledger.items() if blob is None}
    need(len(generated) == 5, "unexpected generated LLVM headers")
    with tarfile.open(HERE/"rust-ci-generated-headers.tar.gz", "r:gz") as tree:
        need({m.name for m in tree} == generated and len(tree.getmembers()) == len(generated), "overlay members")
        for name, (digest, blob) in ledger.items():
            rel = Path(name)
            need(rel.parts[0] in ("llvm", "llvm-c") and ".." not in rel.parts, ("unsafe header", name))
            dest = out/rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if blob is None:
                item = tree.getmember(name)
                need(item.isfile() and item.size <= (1 << 20), ("invalid generated header", name))
                dest.write_bytes(tree.extractfile(item).read())
            else:
                original = src/"llvm/include"/rel
                need(original.is_file() and not original.is_symlink(), ("missing upstream header", rel))
                body = original.read_bytes()
                import hashlib
                oid = hashlib.sha1(b"blob "+str(len(body)).encode()+b"\0"+body).hexdigest()
                need(oid == blob, ("public header blob differs", rel))
                dest.symlink_to(original)
            need(sha(dest) == digest, ("Rust CI header differs", rel))
    return {"source": len(ledger)-len(generated), "generated": sorted(generated),
            "overlay": OVERLAY, "ledger": sha(HERE/"headers.json")}


def build(src, sdk, output):
    src, sdk, output = src.resolve(strict=True), sdk.resolve(strict=True), output.resolve()
    need(not output.exists() and not output.is_relative_to(src) and not output.is_relative_to(sdk), "new dedicated output required")
    available = int(re.search(r"^MemAvailable:\s+(\d+)", Path("/proc/meminfo").read_text(), re.M)[1]) * 1024
    fs = os.statvfs(output.parent)
    need(available > 9 << 30 and fs.f_bavail*fs.f_frsize > 768 << 20, "native build resource floor")
    need(command(["git","rev-parse","HEAD"],src)==LLVM and command(["git","rev-parse","HEAD^{tree}"],src)==TREE,
         "unregistered LLVM source checkout")
    library = sdk/"lib"/LIB
    need(sha(library) == SIGNED and sha(HERE/"neighbor.patch") == PATCH, "signed input digest")
    output.mkdir()
    common = output/"include"
    provenance = headers(src, common)
    build_env = {"PATH":"/usr/bin:/bin", "LC_ALL":"C", "HOME":str(output), "TMPDIR":str(output),
                 "LD_LIBRARY_PATH":str(sdk/"lib")}
    compiler = "/usr/bin/clang++-18"
    compiler_version = command([compiler,"--version"], src, build_env)
    need(re.search(r"clang version 18\.", compiler_version), ("unexpected C++ compiler", compiler_version))
    stats = {"schema":"ohm-machine-source-build-v1","llvm":LLVM,"tree":TREE,"rust_ci":RUST,
             "original_rust_dev_archive":DEV,"original_files":FILES,"headers":provenance,"compiler":compiler_version,
             "cpp_sha256":sha(Path(compiler)), "abi":ABI,"sdk":str(sdk),"signed_llvm":SIGNED,
             "patch":PATCH,"glue":sha(HERE/"pipeline.inc"),"source_arms":{}}
    variants = {}
    for arm in ("stock", "candidate"):
        d = output/("build-"+arm)
        for rel, (blob,digest) in FILES.items():
            dest = d/rel
            dest.parent.mkdir(parents=True,exist_ok=True)
            need(command(["git","rev-parse","HEAD:"+rel],src) == blob and sha(src/rel) == digest, ("unverified source", rel))
            dest.write_bytes((src/rel).read_bytes())
        c = d/"llvm/lib/CodeGen/RegisterCoalescer.cpp"
        if arm == "candidate":
            command(["git","apply","--check",HERE/"neighbor.patch"],d,build_env)
            command(["git","apply",HERE/"neighbor.patch"],d,build_env)
        raw = c.read_text()
        stats["source_arms"][arm] = {"raw_tu": sha(c), "live_interval_header":sha(d/"llvm/include/llvm/CodeGen/LiveIntervals.h")}
        version = d/"exports"
        version.write_text("{ global: llvmGetPassPluginInfo; local: *; };\n")
        for mode in ("plain","inspect"):
            name = ("stock" if arm=="stock" else "strict")+"-"+mode
            lib = output/(name+".so")
            c.write_text(derive(raw,arm,mode=="inspect"))
            args = [compiler,"-I",d/"llvm/include",*ABI,"-I",common,"-DNDEBUG","-O2","-fPIC",
                    "-fvisibility=hidden","-shared",c,library,"-Wl,-z,defs","-Wl,-Bsymbolic",
                    "-Wl,--version-script="+str(version),"-o",lib]
            command(args,d,build_env)
            syms = command(["nm","-D","--defined-only",lib],d,build_env).splitlines()
            need(len(syms)==1 and syms[0].endswith(" llvmGetPassPluginInfo"),("unexpected export",syms))
            loaded = command(["ldd",lib],d,build_env)
            refs = re.findall(r"^\s*libLLVM\S*\s+=>\s+(/\S+)",loaded,re.M)
            need(len(refs)==1 and Path(refs[0]).samefile(library) and "not found" not in loaded,("wrong runtime",loaded))
            need(0<lib.stat().st_size<1<<20,"large native module")
            if mode=="plain":
                need(sha(lib)==QUALIFIED_PLAIN[arm],("does not reproduce the independently tested native module",arm,sha(lib)))
            lib.chmod(0o444)
            variants[name] = {"sha256":sha(lib),"bytes":lib.stat().st_size,"derived_tu":sha(c),"command":list(map(str,args)),"ldd":loaded}
    for name,args in (("wrapper",["-fPIE","-pie",HERE/"wrapper.c"]),("loader.so",["-fPIC","-shared",HERE/"loader.c","-ldl"])):
        command(["/usr/bin/cc","-std=c11","-Wall","-Wextra","-Werror","-O2",*args,"-Wl,-z,relro,-z,now","-o",output/name],output,build_env)
        variants[name]={"sha256":sha(output/name),"bytes":(output/name).stat().st_size}
    stats["variants"]=variants
    (output/"provenance.json").write_text(json.dumps(stats,indent=2,sort_keys=True)+"\n")
    manifest={"schema":"ohm-source-pass-suite-v1","root":str(output),"signed_rustc":str(sdk/"bin/rustc"),
              "signed_llvm":SIGNED,"patch":PATCH,"provenance":sha(output/"provenance.json"),
              "variants":{name:entry["sha256"] for name,entry in variants.items()}}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print(json.dumps(manifest,sort_keys=True))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ("llvm-source","sdk","output"):
        parser.add_argument("--"+arg,required=True,type=Path)
    args=parser.parse_args()
    build(args.llvm_source,args.sdk,args.output)
