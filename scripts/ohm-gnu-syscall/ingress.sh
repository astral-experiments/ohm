#!/usr/bin/env bash
set -euo pipefail
export QA_ROOT="$RUNNER_TEMP/gnu-reviewer-ingress"
mkdir -p "$QA_ROOT/receipts" "$QA_ROOT/inputs"
(cd scripts/ohm-aarch64-versioned && sha256sum --quiet -c SHA256SUMS)
(cd scripts/ohm-aarch64-portable-review && sha256sum --quiet -c SHA256SUMS)
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends gcc-aarch64-linux-gnu g++-aarch64-linux-gnu libc6-dev-arm64-cross qemu-user strace valgrind ninja-build zstd
python3 -IB scripts/ohm-aarch64-versioned/acquire_builds.py
python3 -IB - <<'PY'
import os,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path('scripts/ohm-aarch64-versioned').resolve()))
from version_kit import bind,capsule,rt
from study import load,save,sha
bind()
inputs=rt.ROOT/'inputs/versioned'
product=load(Path('scripts/ohm-aarch64-versioned/qualified-builds.json'))
assert sha(inputs/'sdk.tar.zst')==product['capsule']
sdk=rt.ROOT/'reviewer-sdk'
checked=capsule.verify(inputs/'sdk.tar.zst','C',sdk)
p=inputs/'cargo/cargo'
assert sha(p)==product['cargo_elf'] and sha(sdk/'bin/cargo')==rt.TOOLS['bin/cargo']
temp=sdk/'bin/cargo.new'
shutil.copy2(p,temp)
temp.replace(sdk/'bin/cargo')
save(rt.LOG/'reviewer-sdk.json',{'source':product['source'],'cargo':sha(sdk/'bin/cargo'),'capsule':checked})
PY
