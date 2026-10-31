# Read back the two completed native release smoke jobs

[Native run 41250511954](https://github.com/astral-experiments/ohm/actions/runs/41250511954) at cce370a71a4292c14e58bbfc2c62e8b641e712d9 completed the GNU native build, full corrected release shell and all three linked-worktree cases. Each original job then failed when the final reader mistook a successful Git command for the preceding expected diagnostic. This QA accepts the command sequence in the originals. After Cargo returns 101 with E0277 in src/main.rs, Git must return 0 and report the same common repository. All earlier payload, source, file-identity and full-shell checks run on the original bytes.

| Original | Job | Artifact | Bytes | ZIP SHA-256 |
| --- | --- | --- | ---: | --- |
| GNU | 124682878056 | 13061012439 | 16,920,219 | e4049b6b5c9fed4c089aafdb3f5d3c048577d5acf08a714a82948263e156f770 |
| Darwin | 124682878215 | 13061087498 | 123,855 | 1e761d6a1d6c30660067e48bd6895c26e036276a9ed67e207b9db727dccdc7ba |

The single Ubuntu reader verifies the original repo, workflow, attempt, branch, head, native jobs, runners, terminal steps and GitHub artifact identities. It authenticates the release/global and preceding QA artifact provenance. GNU reopens the Cargo ELF, static libz archive, 524 locked sources, installer and release-shell commands. Darwin reopens original and private 4591 results separately. Each of the three linked-worktree histories must retain its shared artifact identities, 42→73 native edit, unchanged parent value of 42 and real type error. Removing the diagnostic, removing the Git command, changing the reported repository, changing Cargo's exit status or replacing E0277 must each fail on every history. The job uploads only the small JSON readback. Both original jobs retain their original failed conclusions.

After review:

    gh-auto workflow run ci.yml --ref charlie/qa-rc22-static-smoke-readback-20261031 -f source=41250511954 -f reviewed_head="$(git rev-parse HEAD)"

For an offline replay using the two original ZIPs and previously retained official metadata:

    python3 -IB scripts/rc22-complete-smoke/replay_static.py review ORIGINALS result.json

## Native acquisition on cce370a7

Source run [41249054242](https://github.com/astral-experiments/ohm/actions/runs/41249054242) retained the two original -22 distributions, the independent private four-fix Cargo, and every failed supplementary command. Both original packages and the private Darwin overlay completed the full checked-in release shell. The old private GNU Cargo required libz.so.1 and failed the package portability gate. The added linked-worktree check used a different PATH from its donor and observed an actual itoa rebuild in all three completed installations. The predecessor's GNU ZIP is 13060915717 at a47ed6db8ca1291d3753415a79da9c4744d8941cb7f54234b5bf369dc495273f. Darwin is 13060985236 at 984128cb19b8f77352b18d57664e04985f3f68db4777a2c5cfceb5f63b45c1be. Each platform authenticates and independently reopens its own original before collecting new observations.

**GNU** uses only the retained Linux package and installer from original release run 41237680370. The physical builder is original Cargo 8269d772 plus Rust 556a8364, including the original host standard libraries and original Wild. The existing same-repository 46d28e8b and 7bc72b79 Git transfers reconstruct the exact four-fix Cargo source 4591cf45cc10abb19d2456c40b99606e08167f29, tree a2c9a62722e1ef849cb68874e79617c92d165a8b, plus its real lockfile. All 524 locked registry archives must independently match their Cargo.lock checksums before the offline build. Only Cargo is compiled.

The packaging release configuration selects native-static, the Rust bootstrap sets LIBZ_SYS_STATIC=1 and the all-static Cargo feature, and the Ohm release also enables ohm-defaults. A small Git proof connects Rust ceafeeda61cc18293545cc4e4039099cdabc0be3 to the entire tool.rs blob for that rule. Absolute compiler/driver/bin hashes come from the actual package installed by its own archived installer. The build must report the libz-sys build-script static=z directive and produce a real libz.a with the expected public symbols. The new privately built native Cargo must report its intended commit/host and satisfy readelf and ldd. Its actual ELF is retained compressed alongside the build and linkage receipts. The subsequent fresh installation replaces only Cargo and executes the entire unchanged outer release shell with the e8468d0 relink helper, the upstream 1.99.0 analyzer, and a genuine linked-worktree control. This is an unprofiled private Cargo release build. No complete #225 distribution is produced.

An independent GNU devbox control built the same Cargo revision with both release settings. Its 51,047,912-byte ELF had SHA-256 `55c7a99a4228ad2c1b57d92368f930df4ab857f6f9189e2b7cff3430d5773169`. It passed all 141 traced release-source commands, with 120 installed component identities verified. The linked child returned 42 and 73, the parent still returned 42, and the invalid edit produced E0277. The independent product and command receipts have SHA-256 `c692d7d71f97856690b64e8c5cfc34ed5fec28eecf600c5822b5ec6ba042b4a6` and `a00591f6127ecddc2e847dbc610ec0b320f72affc085f054b327b3e65c6ed7aa`. The new hosted builder records its own product and receipts.

**Darwin** restores the original package in two fresh, independent directories. One runs its original 8269d772 Cargo. One replaces only that file with the previously qualified native 4591 binary from 13047576657. It runs the real original registry fixture and the linked Git checkout only. The predecessor ZIP supplies the evidence for the remaining full release shell in each arm.

The initial registry build and linked checkout use the same Cargo proxy directory followed by /usr/bin:/bin, exactly the release shell's registry PATH. Freshness requires the physical parent artifact's device, inode, size and SHA to match for every itoa rlib/rmeta returned by the child. The child must run 42, run 73 on a real source edit, leave its parent at 42, and produce E0277 at the actual changed source for an invalid edit. All ordinary commands, Cargo JSON, native values and partial failures are retained.

The manual workflow allows only the reviewed immutable QA head, original source run 41237680370 and predecessor 41249054242 on this private branch. It uses two native runners with contents/actions read permissions. The original platform artifact identities, stock upstream analyzer hashes and private Darwin Cargo are frozen in registration.json. Both checked-in original shell hashes are checked in the actual sparse checkout. Neither the protected release environment nor publication actions are used.
