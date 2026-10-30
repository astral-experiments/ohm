# Holding Insta's archive timestamp eliminates zero compiles and zero links

On the signed Linux Ohm 1.99.0-21 toolchain, both unchanged builds of the
309-unit Ruff `ty_server` e2e still ran two full rustcs (Ron and the e2e) and one
stock Wild. This happened with the real Cargo timestamp update, and again when
only that update was prevented. The receiver experiment used the same signed
Cargo executable, compiler, Wild and source for all four commands. No timing
was scored. [Completed signed job](https://github.com/astral-experiments/ohm/actions/runs/41137435629/job/124343252030)

| Signed Cargo visit | Allow timestamp | Hold timestamp | Returned result |
| --- | --- | --- | --- |
| Two unchanged visits, each | 2 full, 0 link-only, 1 Wild | 2 full, 0 link-only, 1 Wild | Original ELF; 200 enumerated tests; selected LSP test passed |
| Real reversed trivia edit and restoration, each | 18 full, 0 link-only, 2 Wild | 18 full, 0 link-only, 2 Wild | Edited and restored ELFs each matched its independently empty build |
| Earlier valid native library | 2 full, 1 Wild | 2 full, 1 Wild | Program exited 83 and matched the independently empty valid ELF |
| Malformed replacement | 2 full, 1 Wild | 2 full, 1 Wild | Cargo 101; the physical Wild opened the file and identified the bad linker script |
| Removed valid or malformed library | 2 full, 1 Wild | 2 full, 1 Wild | Original full ELF and passing test |

For valid, malformed and removal, separately deleting the enrolled executable
before running the same command produced the same result. The independently
empty valid and malformed stores initially contained just the higher-priority
`psm/out/libgcc_s.so`. Both really invoked the e2e Wild. An invalid Rust edit
under the hold policy was rejected with the registered compile error, and
repair recovered the exact original ELF. A separately seeded ordinary run
without the adapter and a second run with the adapter unarmed both reproduced
the original 2 full plus 1 Wild. [Frozen workload and controls](https://github.com/astral-experiments/ohm/tree/210bee3f16da74ff34618f06608824edf6385d1b/scripts/insta-archive-diagnostic)

The signed Cargo worker audited **26** timestamp requests on its real process
and **held 14**. Before allowing a hold, the adapter compared every byte of the
existing 8,637,394-byte, 18-member archive on its open fd with an immutable
reference. The two unchanged holds independently bound the same dev/inode
33/7870513 to Cargo's actual thread, to an unchanged mtime and ctime, and to a
successful kernel `utimensat` call with two `UTIME_OMIT` operands.
The e2e's own `--extern insta=…` named that same archive.

The signed e2e still reported a stale *dependency fingerprint* for unit 97
(Insta) on each hold. In the same command, Insta reported unit 192 (Ron) stale,
Cargo found Ron's missing `ohm-foreign-span-bytes` marker and then skipped
compiling Insta. An independent native fingerprint trace identified the Ron
result as `BuiltUnchanged`. Cargo checks and propagates a dependency's stale
status before comparing mtimes in this branch of the code. In the worker queue,
its early-cutoff rule applies to check units and certain build units. The test
executable remains scheduled. The evidence supports stopping this timestamp
approach at the single e2e. [Fingerprint calculation](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/src/compiler/fingerprint/mod.rs#L2205-L2254) · [Signed cutoff eligibility](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/src/compiler/fingerprint/mod.rs#L696-L705)

The existing strict Cargo #293 is a separate natural control. Its unchanged
309-unit build had no Insta archive timestamp syscall. It ran three full
rustcs (the Unicode build script, Ron and the Unicode library), one link-only
e2e rustc, and two actual Wild links. Its complete e2e matched the independent
cold executable and the selected test passed. The strict diagnostic stopped
at its positive-interception prerequisite after those two unwrapped builds,
so the combined GitHub run is red. #293 already preserves eligible skipped
rlib timestamps. The earlier six-visit strict history confirms an unchanged
Insta inode, timestamp and every archive member on that same Cargo, including
the real edit and repair. Its signed counterpart advanced the archive timestamp
at every visit. [Existing strict rule](https://github.com/astral-experiments/ohm-cargo/blob/735e1528ed741015c57676dccf05dbdc0ff7bed1/src/compiler/fingerprint/mod.rs#L607-L619) · [Strict job](https://github.com/astral-experiments/ohm/actions/runs/41137435629/job/124343252430) · [Independent earlier histories](https://github.com/astral-experiments/ohm/actions/runs/41120192553)

The first acquisition switched the compiler-loader environment between the
unwrapped and the hooked visits. Both hosts recompiled 306 units, ran 47 Wild
links and replaced the archive inode before any target operation could be
intercepted. The custody check rejected that attempt. The completed signed
job used an independently empty same-path unwrapped generation followed by
a separately empty diagnostic generation with a constant environment.
[Rejected setup](https://github.com/astral-experiments/ohm/actions/runs/41137063070)

### Independent readback

The reopener checked both full ZIP digests, the actual native exec rows, the
selected kernel timestamp calls and the complete 18-member archive. It decoded
three distinct entire e2e ELFs and checked the physical provider opens, test
results, and matching executable SHA256s. The retained projection records
the native SHA256 for every phase, the complete ELF sizes and sections,
the positive inode/mtime/ctime records, marker and cutoff lines, native
provider identity, and the earlier strict and rejected controls. The full
ZIPs are retained for seven days by the workflow.

| Native acquisition | Archive ID | ZIP bytes | SHA256 |
| --- | --- | ---: | --- |
| Signed Cargo | 13017885347 | 174,028,913 | `5f6d0d47afe1f265e00473b7c23807f8a191ab91bbc3ae6ab19efb72ca516021` |
| Strict Cargo | 13016094804 | 53,795,708 | `35d4afa518277b7039341bcc5b44d207888bfffef2cd50be367e81779163d27d` |

Run the offline readback from the repository root. The mutation tests reject a
removed compile, missing hold, stale executable, accepted malformed library
and missing dependency explanation.

```sh
python3 -IB scripts/insta-archive-diagnostic/result/verify.py --self-test
```

On Linux, the original ZIP reopener uses GitHub and anonymous memory:

```sh
python3 -IB scripts/insta-archive-diagnostic/readback.py \
  --run 41137435629 --head 210bee3f16da74ff34618f06608824edf6385d1b \
  --out /tmp/ohm-insta-reopened
```
