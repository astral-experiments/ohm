#!/usr/bin/env bash
# Run from this evidence packet after installing the pinned compiler/SDK and sources.
set -euo pipefail
root=/tmp/ohm-release-campaign/llvm
packet=$(pwd)
for path in "$root/toolchain/bin/cargo" "$root/toolchain/bin/rustc" "$root/llvm-sdk/bin/llvm-config" "$packet/measure.py"; do
  test -f "$path"
done
mkdir -p "$root/harness" "$root/plugins" "$root/evidence/binaries" "$root/evidence/paired-uv"
cp "$packet/measure.py" "$root/harness/measure-v3.py"
cp "$packet/measure.py" "$root/harness/measure_v3.py"
for name in early-merge-plugin.cpp paired-ruff.py paired-uv.py cold-pairs.py runtime-ruff-final.py runtime-uv.py runtime-uv-final.py actual-flag-pair.py validate-parity.py idle-gate.py; do
  cp "$packet/$name" "$root/harness/$name"
done
flags=$("$root/llvm-sdk/bin/llvm-config" --cxxflags)
# llvm-config deliberately supplies separate compiler arguments; the root has no spaces.
clang++ -O2 -shared -fPIC $flags "$root/harness/early-merge-plugin.cpp" -o "$root/plugins/baseline.so"
clang++ -O2 -shared -fPIC $flags -DOHM_EARLY_FULL_LTO_MERGE "$root/harness/early-merge-plugin.cpp" -o "$root/plugins/merge.so"
clang++ -O2 -shared -fPIC $flags -DOHM_EARLY_FULL_LTO_MERGE -DOHM_PRUNE_BEFORE_MERGE "$root/harness/early-merge-plugin.cpp" -o "$root/plugins/prune-merge.so"
python3 - <<'PY'
from pathlib import Path
import json
p=Path('/tmp/ohm-release-campaign/llvm/evidence/paired-uv/scope-decision.json')
if p.exists():
    plan=json.loads(p.read_text())
    assert (plan['edit_pairs'],plan['cold_pairs'])==(2,1)
else:
    p.write_text(json.dumps({'edit_pairs':2,'cold_pairs':1,'reason':'Reproduce the fixed published UV scope.'},indent=2)+'\n')
PY
