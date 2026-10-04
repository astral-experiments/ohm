"""Hash retained task artifacts after all timing on this host has stopped."""
from pathlib import Path
import hashlib,json,subprocess
root=Path('/tmp/ohm-release-campaign/llvm')
evidence=root/'evidence'
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while b:=f.read(1024*1024):h.update(b)
 return {'bytes':p.stat().st_size,'sha256':h.hexdigest()}
result={'toolchains':{},'harness':{},'source':{}}
for name,sysroot in [('shipping',root/'toolchain'),('stage1',Path('/tmp/codex-cargo-targets/ohm-rust/isolated/release-llvm/bootstrap/x86_64-unknown-linux-gnu/stage1'))]:
 if name=='stage1' and (root/'stage1').exists():sysroot=root/'stage1'
 if not sysroot.exists():continue
 paths=[p for p in [sysroot/'bin/rustc',sysroot/'bin/cargo'] if p.exists()]
 paths += list((sysroot/'lib').rglob('*.so'))
 paths += list((sysroot/'lib').rglob('*.so.*'))
 std=sysroot/'lib/rustlib/x86_64-unknown-linux-gnu/lib'
 paths += list(std.glob('libstd-*.rlib'))+list(std.glob('libcore-*.rlib'))+list(std.glob('liballoc-*.rlib'))
 result['toolchains'][name]={str(p.relative_to(sysroot)):digest(p) for p in sorted(set(paths)) if p.is_file()}
for p in sorted((root/'harness').glob('*')):
 if p.is_file():result['harness'][p.name]=digest(p)
if (root/'llvm-sdk/bin/llvm-config').exists():
 result['sdk_version']=subprocess.check_output([str(root/'llvm-sdk/bin/llvm-config'),'--version','--cxxflags'],text=True)
 result['plugin_compiler_version']=subprocess.check_output(['clang++','--version'],text=True)
if (root/'rust').exists():
 result['source']['git_head']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root/'rust',text=True).strip()
 result['source']['diff_sha256']=hashlib.sha256(subprocess.check_output(['git','diff'],cwd=root/'rust')).hexdigest()
 for name in ['compiler/rustc_session/src/options.rs','compiler/rustc_codegen_ssa/src/back/write.rs','compiler/rustc_codegen_llvm/src/back/write.rs','compiler/rustc_codegen_llvm/src/llvm/ffi.rs','compiler/rustc_llvm/llvm-wrapper/PassWrapper.cpp']:
  result['source'][name]=digest(root/'rust'/name)
(evidence/'final-provenance.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
manifest={}
for p in sorted(evidence.rglob('*')):
 if p.is_file() and p.name!='raw-artifacts-manifest.json':manifest[str(p.relative_to(evidence))]=digest(p)
(evidence/'raw-artifacts-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
print('Recorded',len(manifest),'retained evidence artifacts.')
