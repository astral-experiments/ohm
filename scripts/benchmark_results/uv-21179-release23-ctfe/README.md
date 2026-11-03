# Rust #318 fixes a history-dependent allocation on uv #21179

The released Ohm 1.99.0-23 compiler emitted **585** resolver CTFE allocation records after an incremental edit and **576** in an independently cold build of the same edited source. Adding only Rust #318 brought the incremental result to **576**. The complete sequence of encoded allocation records then matched in content and order. This local correctness test collected zero instruction or wall-time samples. [Compiler PR #318](https://github.com/astral-experiments/ohm-rust/pull/318) · [Upstream uv change #21179](https://github.com/astral-sh/uv/pull/21179).

| Ordinary edited package check | Shipped R | R + #318 (S) |
|---|---:|---:|
| Warm / cold allocation records | 585 / 576 | 576 / 576 |
| Distinct allocation payloads on either visit | 470 | 470 |
| Identical ordered allocation payloads | No | Yes |
| Equal warm/cold public Cargo sidecars | 471 / 471 | 471 / 471 |
| Matching resolver definition rows / direct dependency rows | 16,193 / 454 | 16,193 / 454 |
| Different raw metadata paths / distinct byte pairs among 571 paths | 31 / 11 | 22 / 8 |
| Full prespecified native semantic comparison | Refused on resolver allocations | Passed |
| Rustc processes on unchanged A / first edited B / unchanged B | 0 / 1 / 0 | 0 / 1 / 0 |

Both roles used the identical signed Cargo (`7024b0d2`). Each started from its own cold A, edited to B, rechecked unchanged B, restored A for a separate kernel-observed first B, and rebuilt B from an empty target. The one real compiler after the edit was the `uv_resolver` library with 62 direct externs. The ordinary visits ran this command with no rustc wrapper or injected flags.

~~~sh
cargo check -p uv-resolver --locked --offline -j8
~~~

The only upstream edit was `crates/uv-resolver/src/lock/mod.rs`, from `89c102d09fe5532f5f3e0a0dbf5ea557a6bdd1fd` to `392e0a0aa39f7f03e2efb688e500ec23a1930d36`. In the canonical checkout Git HEAD stayed at A and the working tree exactly matched B. The resolver public hash genuinely changed from A to cold B on both roles. Every warm B public sidecar matched its cold B even on R. Saved compiler reads link `Package::from_annotated_dist` to B’s new private `PackageMetadata::from_distribution`. The two roles each built the original A and B uv executable and ran `uv lock --offline --python /usr/bin/python3` on the same local editable workspace. All four complete lockfiles agreed, including ordinary, optional and development requirements. This fixture observed the linked output. The private constructor’s runtime stack was not recorded.

Eight strings each occurred twice in R’s warm allocation table and once cold. They were `size`, `url`, `upload-time`, `source`, `upload_time`, `path`, `hash` and `name`. `version` occurred three times warm and twice cold. Ten binary payload encodings also differed on R. On S the nine strings all took the original cold multiplicities. The raw resolver metadata still differed in size on S (3,069,164 and 3,069,080 bytes), with 24 opaque lifetimes and four anonymous associated types permuted. All 1,660 keyed source expansion rows agreed for both roles.

## Replay the original

Use Python 3.11 or newer. The default verifier runs offline with the standard library and needs neither an installed Rust compiler nor the original workspace.

~~~sh
sha256sum -c SHA256SUMS
python3 -ISB verify.py
~~~

The verifier opens the two Git commits and their tree/blob proofs, release and producer identities, 142-file SDK inventories, original Cargo command and six kernel traces, the complete metadata/sidecar inventories, all differing metadata owners, six native resolver headers, and four linked outputs. All six native root listings were reread from the original bytes with their owning rustc. Warm and cold B listings reproduce the exact digests from the native runs. The graph headers and digests are included. It decodes the 40 distinct original metadata files (61,496,493 raw bytes) with the same source-bound reader as the native gate. The two original GitHub Sigstore verification responses, published manifest and S producer QA ZIP are included. The large distributions and complete dependency graphs are pinned by their original lengths and hashes.

To reopen both full SDKs and verify every selected component byte and mode, provide the two original archives as well.

~~~sh
python3 -ISB verify.py \
  --signed-sdk /path/to/ohm-1.99.0-23-x86_64-unknown-linux-gnu.tar.gz \
  --corrected-sdk /path/to/rc23-22958-sdk-ctfe_control.zip
~~~

R uses the signed Rust commit `d57fd1515986dccecdcece8da85e651bfb4b81f9`. S is its direct private production child `b5bbf6e74cd71de00a5c805d365e93673f248265`. S’s bundled Cargo was replaced with the signed R Cargo, verified by SHA-256. [Signed release](https://github.com/astral-experiments/ohm/releases/tag/ohm-1.99.0-23) · [S producer job](https://github.com/astral-experiments/ohm/actions/runs/41572266236/job/125707756416) · [Original S SDK](https://github.com/astral-experiments/ohm/actions/runs/41572266236/artifacts/13204110687).

To reproduce the compilation, install each SDK in turn at the same absolute path with that Cargo and use the original `Cargo.lock` in a prefilled offline Cargo home. From a fresh target run the command above twice on A. Apply the sole upstream patch in place, leaving Git HEAD at A, and run the same command twice. Save the first edited `libuv_resolver-*.rmeta`. Move the entire target aside and check B with a fresh target at the identical path. Save the cold product. `originals.tar.xz` includes exact environments, source Git objects, compiled artifact identities, linked project inputs/outputs and original native inventory hashes. `rmeta.tar.xz` contains the content-addressed raw metadata from the observed runs.

To compare two newly captured resolver files with the same reader, run `python3 -ISB verify.py --pair WARM.rmeta COLD.rmeta`. The additional section reports what those two files contain. Its output covers the metadata itself.
