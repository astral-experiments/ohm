# A private Ruff edit after returning to a branch at the same revision

This manual GNU qualification compares rustc E `393b4b05a4bfa3f531a36023846f86236a6b71a9` with its direct child D `d95494a6a63c22222806c06e3d3aa0de504d8e8a`. Both enable `-Zohm-branch-cache=yes`. Cargo `761ea115605c34f11a1cd29afd68812c1e1359dd`, stock Wild, rustup proxies and all 80 other SDK members match. No history is moved, hidden, staged or synthesized. Compiler, native and counter tests use separate stable target/build paths and the real offline developer environment with Ohm defaults.

```sh
cargo +ohm build -p ruff --bin ruff --locked --offline -j4 --message-format=json
```

## Sources and prior results

The 37-artifact qualification at run `41303656721`, job `124839568474`, built D from the exact source tree `d741b524519a14ff43a896b02f3616add279c7b9` and validated both SDKs, seven in-tree tests and three native run-makes. The separate verifier reproduced all 36 ordinary Ruff and 22 provider commands, including same-inode changes, malformed input, recovery and own-empty program comparisons. On the clean return E used Y and compiled AST and edits. D used X and compiled only AST. When X contained a real semantic change, both compilers rebuilt both crates. Complete native/typed outputs and their empty references were checked in that source workload. Two earlier QA refusals, `41301552076` and `41302988864`, remain separate.

The historical E/C counter and schema-3 observer work establish the availability of the observer and counter. No old outcome or pilot clock contributes an E/D sample. The two official ZIPs, selected member sizes, SHA-256 hashes, source readback and prior native job are pinned in `enrollment/donor-source.json`. The worker checks the original Actions metadata, all enrolled archive bytes, the returned native receipts and every installed file. The verified D driver is `f724a33d4d865ac4f3fc235b322a638d6f6534f669e5b1659adabcd04a2221d7`.

## Workload and empty controls

1. On branch Y build Ruff `7b13f01ba1569887a25670820764b24c206da8e5` from empty. Switch to X at its immediate predecessor `b5dba861cc38e3f7fb4524c9ceba3e01a474ea13` and build, then fast-forward X to B and build the real 169-file change. Assert one Cargo-built Ruff executable and the complete 375-artifact typed graph on successful calls. Both refs must physically point to B before the return.
2. Return to Y and change one byte in `crates/ruff_python_ast/src/nodes.rs`, replacing the space in `dead code warning` with a hyphen. Run the same ordinary command and run it again. In full-pilot mode also inject the registered parser E0308, require exit 101 at the edited source statement, restore the exact parser and rebuild. Independently exercise the comment without changing back from X.
3. An independent dirty-donor contact makes the genuine uncommitted Rust body edit `"pyi" => Self::Stub` → `"pyi" => Self::Python` on X at B, then builds. Restore the function on X before returning to Y and applying the same comment. The executable built on X must adopt Python semantics for `.pyi`. The ordinary return and its repeat must recover stub semantics. X and Y have the same commit in both histories.
4. Each role separately builds empty A, B, B+comment and B+function-edit references at the same paths. Successful histories compare the whole CLI and external typed reader with their own corresponding empty executables. The five PYI009 invocations use the Cargo-produced CLI, real JSON diagnostics, normal `.pyi`, `.py`, unrelated extension and both explicit extension overrides. The original real lint/fix/recheck/format, malformed inputs, positive/excluded 64/56-byte external AST type checks and executable reader also run. All these acquisitions occur outside the PMU. The independent reader authenticates every distinct original CLI and reader ELF, recomputes native, diagnostic, graph and disk evidence, and records any cross-role program/loadable discrepancy.

## Structural contact

One independently fresh host takes two clean/dirty histories and four empties per role, totaling 28 ordinary Cargo invocations and zero counter measurements. A live schema-3 contact and exact stock Wild fixture must pass on that host, including both recorded helper exit orderings and the installed-rustc worker gate. Capture actual installed rustc and linker execs for X-B, the return and the repeat. For AST and edits, bind the two pre-return sessions to their actual origin, branch names, optional source revision, publish time, directory inodes, table paths, lengths, SHA-256 and the sampled X-B compiler's full argv. Recheck the same on-disk files immediately before return and authenticate the returned kernel file opens by originating compiler PID. A driver watch calibrates the executable mapping from the already SHA-verified file descriptor and checks the original process mount namespace, visible file and mapped backing identity. It observes the installed compiler without wrapping Cargo or changing its arguments.

Any dirty/clean native mismatch, missing expected files or events, ambiguous mappings, failed resource guard, extra clocks or fresh arm state refusal blocks the pilot. Proceed only after independently replaying the official original and finding a strict subset of full compiler invocations and no additional Wild links on the clean-source return. The study does not prescribe how many full-application units are saved.

## Whole-instruction pilot and storage

After the authenticated contact, two new boots run opposite orders, E then D and D then E. Each boot acquires 46 complete Cargo invocations across four clean references, an unscored stay-X structural history, the complete structural return and the separately empty plain measured return for each role. Only the seven ordinary Cargo-plus-descendants calls on each plain return enter its PMU. The native observer, fanotify, map sampler, output checks, disk scans and CLI executions remain outside all counter windows. Fresh host calibration, inherited retired user-instruction counts, positive nonmultiplexed counters, genuine source and native artifacts, all original calibrator checks and original memory/disk floors apply independently to both boots. The whole return and its structural flank must agree on the actual graph, dirty units, outputs and exit state.

The primary ratio on each boot is E/D retired instructions on the return+comment command, with denominator including Cargo, all actual descendants and any link. Require a ratio strictly greater than two on *each* boot, a strict full compiler reduction, no extra Wild link by owning target and no additional system linker, plus all correctness and physical gates. Retain the separate seven positive raw instruction counts for both roles. Report the inclusive sum, cold and historical charges, subsequent unchanged, invalid and all repair costs separately. A return-specific result is scoped to that command. Any 12-host inference would require a separately reviewed enrollment before its outcomes.

Each successful or rejected-compiler Cargo call retains the complete quiescent target/build pathname-to-inode ledger. The reader compares GNU find, stat, du and Python, charges each allocated physical inode once across both roots, and reports the ordinary raw, packed and build-table aliases, in-place failed sessions, associated locks and all physical bytes. The storage high-water mark is the largest of seven complete post-command censuses. It does not measure a transient in-command target/build peak. The live resource guard independently records host and cgroup floors. Each rebuilt SDK is on the same per-host visible path while selected, with no hardlinks between the two 81-file installations.

## Reviewer entry points

Both manual modes take a reviewed QA head on branch `charlie/qa-ruff-same-revision-donor-full-20261101`. Mode `contact` accepts no prior outcome. Use `contact_review.py` with the original ZIP, official run/job/artifact JSON, immutable observer checkout and reviewed head to obtain the contact certificate. Mode `full-pilot` also requires the exact contact run, original ZIP SHA-256 and SHA-256 of that certificate. Use `reopen.py --help` for the independent two-position reader. Preserve a failed or incomplete original at its registered position and contribute zero clock interpretations until its independent gates pass.

The first dispatch runs only the contact. From an authenticated packaging checkout, substitute the locally reviewed commit for `HEAD` and the resulting official identifiers for the three environment variables.

```sh
head=$(git rev-parse HEAD)
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-ruff-same-revision-donor-full-20261101 \
  -f mode=contact -f reviewed_head="$head"
s=scripts/ctfe-crossover-pilot
python3 -IB "$s/contact_review.py" offline --run "$CONTACT_RUN" --head "$head" \
  --observer-source "$OBSERVER_SOURCE" --official "$OFFICIAL_METADATA" "$CONTACT_ZIP"
```

The official metadata directory holds `run.json`, `jobs.json` from attempt one, and `artifacts.json`. The observer checkout must be the immutable schema-3 source listed above. A full pilot needs a separate reviewer-approved dispatch with `mode=full-pilot`, `contact_run`, `contact_sha256` and `contact_readback_sha256`.
