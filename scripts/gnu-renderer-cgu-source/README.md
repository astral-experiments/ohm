# Native GNU source qualification for renderer codegen placement

This private QA ref authorizes one unscored native job only after its exact packaging commit is reviewed. The independent ordinary-workflow registration is sealed in `ORDINARY-STUDY.md` (SHA-256 `70076984ab6feb82a8a9eae43cb9a9c34eec7a9cc42a50305c018391c14afe66`). The two corrected source identities are registered in `ORDINARY-STUDY-V2.md` (SHA-256 `1697b1e098ef8398714d55023da7a46c2838d19447108176eb8606bd66296a01`). It builds the GNU compiler three times from clean Rust source at the same physical path. Its twelve native run-make visits and ordinary Rust/Cargo smoke programs test membership and preservation of existing behavior. The job produces reusable toolchains for a separate ordinary Ruff experiment.

| Role | Native Rust source | Compiler subtree |
| --- | --- | --- |
| P, live #278 base carrying #284 | `4e7c5b1f765b24ccd585d8ddb7eeae99a02b514e` | `b429aa02503b16993d9b8f94a6ab17f4f3bfaa01` |
| F, standalone derived forwarders with coverage guard | `51e72261c0b36dfd49c078b35732956d6b950e8e` | `84107218ae14ae41937c2bbea83b84338ac18d9d` |
| C, forwarders plus callable families and scoped higher-ranked borrows | `11876886792274b44a9a37567fbac57bf843a24c` | `d4b3be137de57d758c2f68712ffb5c819496ec1c` |

C is a direct child of F, which is a direct child of the live P. P contains the #284 guidance at `f0750c162dc7f095b1c8c0caa9ca3894359404a1`. The complete compiler, library, tests and bootstrap trees of P still equal signed -21 source `c79998a5cd143c445a4b2528f20953b176a65c5d`. Only `AGENTS.md` and `src/ci/citool/Cargo.lock` differ. The actual full-index two-dot diff is 15,014 bytes (SHA-256 `fb920ee153c81895b3265fe729a693968dd68e3258ef24568b6b51c8d10e9971`). That identical diff takes the final signed-source prototype `19d9b2a1d88e470ea2bea2e29b3b65a74ab08850` to the pre-lint live C at `b79ec99c44772853c313161bee2bbfaecc80e0de`. The current F and C differ from their previous trees only in the import and spelling of `Ty` in the partitioner. The source verifier reconstructs each tree and checks those exact bytes. The signed original forwarder `e420faa7fc34004b5e56b2c9f1456ae2ee5eab50` remains a reconstructible historical control.

All three builds use library tree `4f7a8f755164dc68fff80790db8a844ae030fd03` and bootstrap tree `1dcf3e6b142ba5c132f7a2370dffa6ba090b15e1`. The source-bound F and C share the exact coverage-bearing forwarder fixture. C adds the checked-in test for higher-ranked function pointers with a sole owner and with mixed owners. A future source change requires fresh qualification. No release action is present.

## What the worker actually runs

The workflow checks every source, packet and registration file against `SHA256SUMS`, then reconstructs the public b940 upstream, pinned backtrace submodule, signed private history and the live #278 history. A 112,293-byte pack (SHA-256 `12277c6b2c405ea921acf59f7a1ed94eee5f4a069b8dc777c6408d49e998759f`) carries the 263 missing commit objects, 340 trees and three blobs missing from the original signed source closure. It preserves all original parent edges. The independent offline replay started with all 68,684 original signed objects in a fresh repository with no alternates and no remotes. Full Git fsck passed on the signed baseline alone, after installing the live history, and again with all final role and historical prototype commits. See `packet/lint-complete-baseline.json` for this registration and `packet/complete-baseline.json` for the first source registration. The worker reconstructs two corrected role commits and nine historical control commits with a separate Git index. It verifies the actual signed-to-live changes both before the experiment and after reconstructing its strongest candidate. Every role uses the same checked-in `./x --ci false --set build.submodules=false --set rust.omit-git-hash=true --set rust.debug-assertions=false --set rust.lto=off --set llvm.download-ci-llvm=true build --stage 1 -j8 --host x86_64-unknown-linux-gnu --target x86_64-unknown-linux-gnu compiler/rustc library src/tools/rustdoc`. This build and all four suites run through the executable `./x` platform launcher. Its Git blob `768ed1674641e020c4fb9985d53c197ca5bf3e16` forwards the arguments unchanged to `x.py` blob `928a7496cb70ef2a6caf8e890fb09f12883a26e3`. Each role authenticates both working files, their executable modes and the physical Python 3.13 that the Linux launcher selects on PATH. The stage0 compiler, stage0 Cargo, stage0 metadata, Bors revision, LLVM key and submodule are verified independently for every role. Build and test commands retain raw outputs, status, physical source identity, arguments, elapsed time, maximum RSS and free bytes. Native controls have precedent at exact packaging revisions `d1e77f9a` (run 41157899149) and the named reporter from run 41170783373.

| Actual named run-make test | P | F | C |
| --- | --- | --- | --- |
| caller-local-codegen | pass | pass | pass |
| ohm-split-large-cgus | pass | pass | pass |
| ohm-derived-forwarder-cgus | fails first missing `<&Derived as std::fmt::Debug>::fmt` derived placement | actual F fixture passes, including coverage refusal | identical coverage fixture passes |
| ohm-caller-drop-family | fails original fixture-module `scoped` placement at line 41, before the HRTB assertions | same intended failure | passes, including sole and mixed HRTB owners |

Missing benchmark fixtures are supplied only *after* the clean compiler and native standard libraries compile. The parent derived failure must identify the original volatile external CGU at line 37. The callable failure must identify the original fixture-module CGU at line 41. A positive requires one named passing run-make test and its compiler status. A negative requires one named failed test, the precise old placement and the expected bootstrap status. A compiler or fixture error cannot satisfy the named placement failure. All native runtime bytes are rehashed after the tests. The next role gets a fresh private bootstrap build directory.

The first parent bootstrap built the standard library, then a separate rustdoc bootstrap recreated the stage1 sysroot without libcore. Each role now requests the compiler, library and rustdoc in one invocation. After the four test invocations the worker compares every retained SDK file, reassembles all three components and compares the complete physical manifest to its original. [First parent run](https://github.com/astral-experiments/ohm/actions/runs/41183356225)

The second run built P, passed its required run-make and client controls and preserved all 81 SDK files. Its F build stopped on a denied qualified-type lint. The corrected F and C keep the same algorithm, fixtures and warning policy. [Second source run](https://github.com/astral-experiments/ohm/actions/runs/41184069572)

Every normal installation gets Cargo #301 `c18e91b514b2c4e4966c9ab03232c804af3e1b57` (tree `bf643fa158734642bfee4a2aa8eff4d98bd8a09c`, complete executable `9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826`) and the unmodified signed -21 Wild (`0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5`). Released Cargo #294 (`4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e`) and the released Rust tools are retained in separate release provenance.

With `cargo_input=archive`, the worker reopens the two original #301 artifact ZIPs from run 41081958994, including the exact native build and unit receipt. With `cargo_input=source`, it independently builds Cargo from the archived exact Git source using the original 119-member AArch64-capable compiler SDK, the original paths, the fixed OpenSSL build clock and real unit test. The [previous byte-for-byte recipe](https://github.com/astral-experiments/ohm/tree/1e3b37ac28ed11a638d3ba2093b54d83ca10ce14/scripts/ohm-gnu-syscall/source-rebuild) uses retained source and published -20, independent of the expiring #301 binary ZIP. Both inputs enforce the identical 50,945,080-byte Cargo. Source mode costs an extra source compiler stage, Cargo/OpenSSL native build and selected tests on the same worker.

The prospective operational surface includes every fresh native GNU standard-library file and host linker, rustc, rustdoc, the driver, LLVM dynamic libraries, exact #301 Cargo and signed Wild. The role must use matching Rustup proxies, its complete host std and the actual stock Wild on ordinary Cargo builds and test harnesses. Each executable is run after the command and the named harness inventory is checked. F and C consume P's real rlib with the same native source stamp. A separate observation tries released-compiler rlib → source-stage compiler and the reverse. A real E0514 with status 1 is recorded if the released and stage1 version stamps differ. Those probes separate the stage experiment from upgrading a published installation.

All complete non-driver files must match P by name, size, permissions and raw SHA-256. A difference is a failed gate, with the independent manifests, first divergent originals, whole P kit and prior physical driver retained. No normalized file match can pass. On success the compressed archive contains P's complete native SDK once, the two separate physical drivers, full manifests and raw ELF hashes. `restore.py` reopens all three after sealing and checks each donor and complete member. Restores use fresh directories.

## Rerun after approval

Use the dedicated packaging branch and full reviewed SHA. Switch the Cargo input to `source` after original artifacts expire. The branch must still point to the reviewed workflow.

```sh
qa=$(git rev-parse HEAD)
branch=charlie/qa-gnu-renderer-cgu-source-20261031
/home/dev-user/.local/bin/gh-auto workflow run ci.yml -R astral-experiments/ohm --ref "$branch" -f reviewed_head="$qa" -f cargo_input=source
```

Verify the run's head, attempt, terminal job and both official artifact digests before extraction. Then, for example, install a fresh F role with

```sh
python3 -IB scripts/gnu-renderer-cgu-source/restore.py downloaded-transfer ./fresh-F F --qa "$qa" --run "$approved_run" --attempt 1
```

The job is bounded to one `namespace-profile-ubuntu-24-04-16` runner, eight build workers, at least 32 GiB free disk and 6 GiB available memory, and a 300-minute timeout. Source and stage paths stay fixed; per-role native builds are serial. A previous 68-entry matched parent receipt had 739,006,129 uncompressed bytes, with a 142,785,264-byte driver. Plan for roughly 1.1 GiB uncompressed transferable payload across the three roles and scratch overhead for one compiler build at a time. Local dry checks use about 30 MiB of transient Git indexes in tmpfs and never build a compiler.
