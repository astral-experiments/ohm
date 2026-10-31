# Ohm 1.99.0-22 native marker qualification

The first two jobs build a source-qualified native stage1 compiler, rustdoc and matching host libraries at `625207d26ce4449c9c95d871c88cfb50e904c09f`. Both compile the proposed Cargo pin `2554a1dfaf22474b360a4298883acf41f82bd78f` and review merge `4591cf45cc10abb19d2456c40b99606e08167f29` with the release profile, all-static and ohm-defaults, release channel dev. The official distribution build, PGO, packaging and signing are separate. The frozen manifest is from [Ohm #223](https://github.com/astral-experiments/ohm/blob/8b2380c1aa9d1707441e79fc549f156516f1aced/toolchains/1.99.0/22.json).

Prior same-repository source kits supply public Rust history and the exact earlier Rust and Cargo trees. New non-thin Git packs cover the seven actual release commits and all 17 Cargo commits, including the merge's two parents. Every new object was hashed as Git data. The Cargo seed, materialized source paths and modes, two complete trees, Rust compiler/library/bootstrapping trees, stage0 tools and linked binaries have separate identities. Only the published GNU Wild 0.11.0 executable is copied from the authenticated -21 package; its Cargo bootstraps Cargo with defaults disabled. The Apple SDK uses the system Xcode linker and records its physical digest. The compiler and libraries under test always come from the new source.

## Reusable artifacts

The job names are `Native SDK (x86_64-unknown-linux-gnu)` and `Native SDK (aarch64-apple-darwin)`, with workflow job id `sdk`. Their artifacts are named `rc22-native-sdk-<triple>`. Read the official workflow run and job status, verify the exact source SHA and official ZIP's SHA-256, then use the version of the receiver at that same QA commit.

```sh
python3 -IB scripts/rc22-native/sdk.py reopen extracted-official-artifact fresh-native-root
fresh-native-root/sdk/bin/rustc -vV
fresh-native-root/roles/fourfix/cargo -Vv
```

The ZIP contains exactly `receipt.json`, `members.json` and `kit.tar.zst`. The receipt binds the run, QA head, source trees, release features, source inventory, full rustc and rustdoc versions, compiler driver, stock linker, Cargo binaries and payload digests. The receiver streams and authenticates each regular archive member in an empty destination. `sdk/bin/cargo` starts pinned. An atomic replacement from `roles/fourfix/cargo` switches only the reader.

## Marker and provider cases

The real pinned Ruff lock supplies zmij 1.0.10 on both hosts, plus objc2 0.6.3 with objc2-encode 4.1.0 on arm64 macOS. The controlled Rust application uses the registry API and directly calls a real external static provider. Its build script emits two fixed -L locations and reruns only on build.rs. The register-only zmij comment emits the original marker both on GNU (general register) and Darwin (NEON vector). On Darwin objc2's `mov fp, fp` emits v2. The terminal Rust source contains no assembly. The ordinary measured unit is the small binary with these actual locked dependencies. This is a correctness control, not a full Ruff build or a performance measure.

Each dependency has independent pinned, fourfix and warmed pinned→fourfix histories. At the same visible paths every ordinary build has a separate independently empty reference and a separate retained reference forced via ordinary package-only Cargo clean. Three static objects return 17, 29 or 41 and carry their own unique native string. The program must call the provider and report its tag; the complete ELF or Mach-O must physically contain exactly the matching tag. The sequence covers higher-priority appearance, same-size/inode/mtime replacement, malformed bytes, repair, removal, missing-both, restoration and an independent E0308/repair control. An exact kernel process ledger binds GNU Wild; Endpoint Security binds Xcode ld. Stored raw and Cargo-translated dep-info is tied to the actual registry compiler artifact's directory. The BLAKE3 LNK1 trailer is decoded and checked. The pinned original-v1 negative, the fixed same-path migrated output and the v2 positive all have separate assertions. Genuine source error 101 and native linker error 101 have opposite terminal-link expectations.

Successful GNU warm and force outputs must match their independently empty whole ELF. On macOS, where raw output can embed different CGU filenames, the established prior receiver checks all executable bytes with its authenticated same-path N_OSO/UUID/signature comparison and independently hashes every saved native object. Full raw outputs, kernel events, stream diagnostics and all refusals are retained in a per-platform provider ZIP. The 11 phases, three histories and three lanes produce 99 ordinary commands per emitter. An ordinary `-Zohm-defaults=no` release build, production PGO artifact and Windows or musl are outside this matrix.

## Dispatch after review

From the isolated QA checkout and under the verified OSS account, compare the local head with the published branch, then dispatch just this workflow. The previous -21 source is retained as the historical control.

```sh
BRANCH=charlie/qa-rc22-native-markers-20261031
OID=$(git rev-parse HEAD)
test "$(/home/dev-user/.local/bin/gh-auto api repos/astral-experiments/ohm/git/ref/heads/$BRANCH --jq .object.sha)" = "$OID"
/home/dev-user/.local/bin/gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref "$BRANCH"
```

The source of the classifier and both Cargo readers are available at [the release compiler](https://github.com/astral-experiments/ohm-rust/blob/625207d26ce4449c9c95d871c88cfb50e904c09f/compiler/rustc_codegen_llvm/src/asm.rs#L1579-L1618), [marker emission](https://github.com/astral-experiments/ohm-rust/blob/625207d26ce4449c9c95d871c88cfb50e904c09f/compiler/rustc_interface/src/passes.rs#L712-L717), and [the pinned Cargo reader](https://github.com/astral-experiments/ohm-cargo/blob/2554a1dfaf22474b360a4298883acf41f82bd78f/src/compiler/fingerprint/dep_info.rs#L604-L620).


The Apple-only continuation preserves run 41212542603 and its GNU SDK job.
The original Xcode 16.0 worker refused its archive listing during protocol
preflight, before Rust source acquisition. The continuation qualifies the actual
archive index followed by one byte-identical provider object. It records the
platform listing separately. Six native Xcode archive/object pairs from
41114554812 used `__.SYMDEF SORTED`, while LLVM Darwin format used `__.SYMDEF`.
Both SDKs and both Cargo source identities stay fixed.
