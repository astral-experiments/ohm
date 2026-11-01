# Verify a private native export rename through Cargo

The original proposed Ohm `-22` panicked on both Linux and Apple silicon when a private, retained static changed its exported symbol. Retrying panicked again. On both platforms the revised compiler produced the newly requested native value, rejected an unrelated type error, repaired the same working directories and restored the previous value after reversing the edit. It also passed the two private-implementation regressions that caught the first attempted fix. [Linux artifacts and compiler cases](https://github.com/astral-experiments/ohm/actions/runs/41254380956) · [Darwin ordinary Cargo artifact](https://github.com/astral-experiments/ohm/actions/runs/41254660609/artifacts/13062950269) · [Linux and macOS compiler CI](https://github.com/astral-experiments/ohm-rust/actions/runs/41254499218)

The Darwin test used the release installer, fixed Cargo `4591cf45`, and both original and revised rustc with the same stock Xcode linker. The corrected binary and test each returned 17 before the edit, 83 after it, and 17 after reverting. Machine code and initializer section bytes matched the independent empty build on the edited source. The evidence preserves the individual full-file hashes for these Mach-O files. [Per-command results and section digests](darwin.json)

## Ruff’s locked defmt

In Ruff’s locked `defmt` 1.1.0, renaming its exported wire-version marker from 4 to 5 made the original `-22` compiler panic on both the stale consumer and the repaired consumer. The revised compiler issued the real undefined-symbol diagnostic for a consumer still asking for 4. The repaired consumer asking for 5 linked, ran, and matched the empty build byte-for-byte. Changing the marker’s value from 0 to 29 also changed the warm executable’s result and matched an independent clean build. [Original](original-defmt.json) · [Corrected](corrected-defmt.json) · [Ruff lockfile](https://github.com/astral-sh/ruff/blob/93526150df078af7dd8fc4226cdcc469539d2001/Cargo.lock)

The optimized Linux distribution built from Rust `1bc7b35699` and Cargo `4591cf45cc` passed the same twelve visits. Both warm attempts with the obsolete symbol and the independent empty build exited 101 with the expected missing-symbol error. The initial, repaired and changed-value executables each matched their own empty build byte for byte and produced the expected native value. The distributed Cargo binary had SHA-256 `39757e62befda4ebee24110766bd63fb9cbbc88e694f3df4ef7121763b3b2d91`. [Twelve Cargo outcomes and ELF hashes](optimized-gnu-defmt.json) · [Optimized GNU distribution](https://github.com/astral-experiments/ohm/actions/runs/41256793646/artifacts/13064288126)

## Repaired diagnostic in Ruff’s `ty_project`

The optimized Linux package also passed a 275-unit `cargo check -p ty_project` after reversing Ruff’s uv dependency edit. Each injected type error returned 101 with `E0308`. Both repairs and an unchanged retry returned success and printed exactly the same deprecation warning as a check from an empty target. Independent typed clients read the repaired, repeated and empty library outputs and accepted the valid program and rejected the invalid program with `E0308`. [Cargo verdicts, target rosters and external readers](optimized-gnu-ty-check.json) · [Original Ruff edit](https://github.com/astral-sh/ruff/commit/32c5cd5daba51d9c3da691c5b43afa6a7a4bb731)

The warmed and empty `ty_project` metadata differed by 127 bytes in size on both the previous and proposed compilers. On the proposed compiler both builds used the same absolute output paths. In its 422-line decoded metadata listing, all 28 differing lines differed only in hash values. Those same lines also differed on the previous compiler. [Source and binary identities, decoded hashes, and line comparison](ty-check-metadata.json)

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
