#!/usr/bin/env bash
# Uses the same unrelated rustc-perf workloads as the PGO training job.
bolt_instrument() {
  local filename=LLVM-23.1.5-Linux-X64
  local archive="$RUNNER_TEMP/$filename.tar.xz"
  bolt_root="$RUNNER_TEMP/bolt"
  mkdir -p "$bolt_root/profiles"
  curl -fsSL --retry 3 "https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.5/$filename.tar.xz" -o "$archive"
  echo "f72edb0b36580ece7f52e23858f00c18fad4e87395ea7ad05d7e55c39f8fc78a  $archive" | sha256sum --check
  tar -xJf "$archive" -C "$bolt_root" --strip-components=1 --occurrence=1 \
    "$filename"/{bin/llvm-bolt,bin/merge-fdata,lib/libbolt_rt_instr.a,lib/libbolt_rt_hugify.a}
  local drivers=("$stage"/lib/librustc_driver-*.so)
  test "${#drivers[@]}" = 1
  driver="${drivers[0]}"
  cp -L "$driver" "$bolt_root/driver.so"
  "$bolt_root/bin/llvm-bolt" -instrument "$bolt_root/driver.so" \
    "--instrumentation-file=$bolt_root/profiles/driver.fdata" \
    --instrumentation-file-append-pid -o "$bolt_root/instrumented"
  mv "$bolt_root/instrumented" "$driver"
}

bolt_optimize() {
  "$bolt_root/bin/merge-fdata" "$bolt_root"/profiles/*.fdata > "$bolt_root/merged.fdata"
  test -s "$bolt_root/merged.fdata"
  "$bolt_root/bin/llvm-bolt" "$bolt_root/driver.so" -data "$bolt_root/merged.fdata" \
    -o "$driver" -reorder-blocks=ext-tsp -reorder-functions=cdsort \
    -split-functions -split-strategy=cdsplit -split-all-cold -jump-tables=move \
    -icf=all -update-debug-sections
  sha256sum "$bolt_root"/{bin/llvm-bolt,driver.so,merged.fdata} "$driver" | tee "$kit/bolt.sha256"
}
