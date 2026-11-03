# Conflicting checksums for two spellings of the same Rust input

On Linux x86_64 this packet exercises [Ohm Cargo #436](https://github.com/astral-experiments/ohm-cargo/pull/436) with two source-built rustcs. The first compiler records the actual byte buffer at each read. The [Rust #347 compiler](https://github.com/astral-experiments/ohm-rust/pull/347) additionally recognizes when two names designate the same Rust path and withholds a digest after conflicting reads.

The application uses an array length to require the first byte of `include_bytes!("payload.bin")` to be 17. Between that read and `include_bytes!("./payload.bin")`, a local procedural macro saves 29 at the same offset and restores the file’s original nanosecond mtime. The second array requires 29. The first compilation succeeds with these two distinct buffer contents. Every later check of the untouched source must report E0308 because the first read now returns 29.

* Cargo `9f2bf035` plus the first compiler wrote two correct BLAKE3 lines to the raw dep-info. Cargo’s v4 fingerprint kept only the second digest. The next warmed check returned success with zero real consumer rustcs. A new empty target for the unchanged source ran the consumer and reported E0308.
* Swapping only Cargo to `4a6de785` at the same executable, source, target, and build paths made the very next check run rustc and report E0308. That build used pre-existing on-disk v4 fingerprints. Fresh v5 records also gave E0308 on the first unchanged check with each compiler.
* For the first compiler, v5 retains both conflicting inputs. Rust #347 emits an explicit input without a checksum and v5 honors it. When both observed values agree, both pairings remain fresh with zero real consumer rustcs.
* After repairing the array length, both native builds in each of the three histories produced byte-identical ELFs. Reopening those ELFs and running them prints `29 29`.

The independent reader reopens 26 Cargo commands, 20 consumer rustc invocations and three pairs of native ELFs. It checks the original JSON diagnostics, kernel exec traces, typed Cargo fingerprints, original dep-info rows, BLAKE3 of both four-byte payloads and native behavior. The 113 distinct bodies occupy 214,011 bytes compressed. Earlier local attempts refused an unavailable ptrace capability, a newly added second native-target fingerprint during file selection, and the fixed 8 GiB resource guard. The final registered run selected the previously recorded physical check fingerprint path across the binary-build phase.

## Reopen

Run from this directory on Linux x86_64 with Python, `zstd` and `b3sum` installed.

```sh
python3 -IB reopen.py
```

To rerun the direct commands, provide the native Cargo from the [v4 factory](https://github.com/astral-experiments/ohm/actions/runs/41597635908), the native Cargo from the [v5 factory](https://github.com/astral-experiments/ohm/actions/runs/41604084199), and the SDK roots for the candidate role of the [first compiler](https://github.com/astral-experiments/ohm/actions/runs/41599633807) and the [Rust #347 compiler](https://github.com/astral-experiments/ohm/actions/runs/41602014524). The shell variables below name those local, authenticated files. Pick a new work path. The receiver checks all four native tool digests, keeps each SDK at a stable path, requires at least 15 GiB of free disk and stops immediately if available memory drops below 8 GiB.

```sh
python3 -IB replay.py prepare --root "$NEW_WORK" --old-cargo "$CARGO_V4" --c1 "$RUST_C1" --c2 "$RUST_C2"
python3 -IB replay.py verify --root "$NEW_WORK" --old-cargo "$CARGO_V4" --c1 "$RUST_C1" --c2 "$RUST_C2" \
  --candidate "$CARGO_V5" --sha 9d81d7fc7747e6202d79c1daaa5e5420ed69af7fc1799fc253f134634d4a7b60
```

The Cargo reader checks the observations supplied by rustc. A compiler that reopens each filename late can report two identical current-path hashes even when its earlier reads saw different bytes. Rust #347 supplies the consumed-buffer side of that contract.

The format update makes older checksummed records rebuild once. The previously measured signed RUF009 check namespace contained 32 v4 and 328 checksumless v2 records. Its native-build namespace contained 32 v4 and 318 v2 records. These counts describe the records at risk. A separate real Cargo upgrade measures the actual downstream work.
