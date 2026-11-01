# Verify a private native export rename through Cargo

The original proposed Ohm `-22` panicked on both Linux and Apple silicon when a private, retained static changed its exported symbol. Retrying panicked again. On both platforms the revised compiler produced the newly requested native value, rejected an unrelated type error, repaired the same working directories and restored the previous value after reversing the edit. It also passed the two private-implementation regressions that caught the first attempted fix. [Linux artifacts and compiler cases](https://github.com/astral-experiments/ohm/actions/runs/41254380956) · [Darwin ordinary Cargo artifact](https://github.com/astral-experiments/ohm/actions/runs/41254660609/artifacts/13062950269) · [Linux and macOS compiler CI](https://github.com/astral-experiments/ohm-rust/actions/runs/41254499218)

The Darwin test used the release installer, fixed Cargo `4591cf45`, and both original and revised rustc with the same stock Xcode linker. The corrected binary and test each returned 17 before the edit, 83 after it, and 17 after reverting. Machine code and initializer section bytes matched the independent empty build on the edited source. The evidence preserves the individual full-file hashes for these Mach-O files. [Per-command results and section digests](darwin.json)

## Ruff’s locked defmt

In Ruff’s locked `defmt` 1.1.0, renaming its exported wire-version marker from 4 to 5 made the original `-22` compiler panic on both the stale consumer and the repaired consumer. The revised compiler issued the real undefined-symbol diagnostic for a consumer still asking for 4. The repaired consumer asking for 5 linked, ran, and matched the empty build byte-for-byte. Changing the marker’s value from 0 to 29 also changed the warm executable’s result and matched an independent clean build. [Original](original-defmt.json) · [Corrected](corrected-defmt.json) · [Ruff lockfile](https://github.com/astral-sh/ruff/blob/93526150df078af7dd8fc4226cdcc469539d2001/Cargo.lock)

## Ruff parser edit

The baseline and revised toolchains ran 24 ordinary Cargo checks, builds and test builds apiece, plus six same-command repeats. The workload reverses the real parser change for `from x import (*)`, tries invalid Rust, repairs it, then checks an independently empty build. The full target rosters, nonfresh sets and typed diagnostics agreed. Both compiled integration-test inventories agreed. On each reopened fixture binary all 558 tests passed on the original source. Exactly the intentionally mismatched snapshot failed on the edited source. [Comparison](corrected-ruff.json) · [Source change](https://github.com/astral-sh/ruff/commit/a50dc58628691ee00a21809e19bdea71958e4f3c)

The non-PGO stage1 parent and candidate both sometimes changed one byte of the GNU `.rodata` section header and the corresponding 32-byte build ID on another link. All other bytes matched per source state. Direct replay with the same 164 candidate link inputs and the same Wild 0.11.0 binary reproduced the difference by changing only its thread count. With the pre-fix release distribution’s inputs, the same thread comparison produced identical links. [Physical original and revised fixture files and link counts](gnu-fixture-link.json)

Four GNU assembler objects reproduce the existing linker behavior without invoking Cargo or rustc. On the signed GNU linker, one thread gave the resulting `.rodata` an entry size of 0 and two threads gave it 2. Both executables exited 17. From the assembler directory, run this with `WILD` set to the physical GNU Ohm linker of SHA-256 `0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5`. [Inputs and original outcomes](assembler)

```sh
dir=$(mktemp -d)
for obj in entry data000 data001 data002; do
  as "$obj.s" -o "$dir/$obj.o" || exit 1
done
for threads in 1 2; do
  "$WILD" --build-id --threads="$threads" -o "$dir/out-$threads" \
    "$dir/entry.o" "$dir/data000.o" "$dir/data001.o" "$dir/data002.o" || exit 1
  readelf -WS "$dir/out-$threads" | awk '/[.]rodata +PROGBITS/'
  status=0
  "$dir/out-$threads" || status=$?
  test "$status" -eq 17 || exit 1
done
```
