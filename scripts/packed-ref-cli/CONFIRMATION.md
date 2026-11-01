# Reopen the six-host D/Q confirmation

The preregistration is `inputs/six-plan.md`. Its trace-count clarification is `inputs/six-inventory.md`. One fresh worker runs 46 real Cargo commands, including 14 hardware observations and 16 separately traced structural visits. The sole primary is the first ordinary X-B fast-forward build. D-first slots are 01, 03 and 05. Q runs first in 02, 04 and 06. `inputs/six-excluded.json` binds the original 143 previous boots and 144 jobs/runners, including the excluded 11.143× contact, both source attempts and the six earlier E/D hosts. The prospective live-job supplement adds seven physical Namespace runner/job identities and four independently authenticated default-mode boot UUIDs, bringing the union to 147 boots and 151 jobs/runners.

On the coordinator, use this exact QA checkout and the originally enrolled six-host transfer helper. The latter is source-hashed before import and performs a complete SHA-256/length reread of every sealed Linux memfd. `ROOT` must be an existing task-owned direct child of the coordinator's .cache directory with more than 512 MiB free.

```sh
python3 -IB scripts/packed-ref-cli/coordinate.py rehearse --head "$REVIEWED_HEAD" --run 41331687491 --root "$ROOT"
python3 -IB scripts/packed-ref-cli/coordinate.py bind --head "$REVIEWED_HEAD" --run "$NEW_RUN_ID" --root "$ROOT"
python3 -IB scripts/packed-ref-cli/coordinate.py collect --head "$REVIEWED_HEAD" --run "$NEW_RUN_ID" --root "$ROOT"
```

The first command re-executes the eight original ELF bodies from the excluded contact and reads its 46 visits. The second binds the six fresh jobs before any has an outcome or artifact. The third authenticates all six complete originals for identity, then independently reopens the same six for native correctness and counters. All outcomes and failures keep their original positions. The ZIPs remain in anonymous RAM. Each complete successful position preserves a bounded archive-member projection and the independent native/PMU report including every user/system CPU time, raw PMU field and command-end allocation.

For an offline per-host replay, pass its original ZIP, all original official GitHub metadata and all-six boot admission in one directory. Supply the same source-qualified kernel, calibrator, observers, and earlier identity-only E/D admission specified in the excluded contact's PLAN.md.

```sh
python3 -IB scripts/packed-ref-cli/review.py --position 02 --head "$REVIEWED_HEAD" --official "$METADATA" --zip "$ORIGINAL_ZIP" --kernel "$KERNEL" --calibrator "$CALIBRATOR" --observers "$OBSERVERS" --concurrent-admission "$E_D_SIX_BOOT_RECORD" --concurrent-sha256 eb7aa0c79de4d207bd6ceb334b275d069bc3a435832d5ce0a558c87efee39c86
```
