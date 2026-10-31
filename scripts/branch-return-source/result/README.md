# Native qualification for Full and Packed

The reviewed Rust #274 source `c6fe8ecda65452c105f85367a009af80cbb5efbc` and its packed-object child `0afbeff303d3658bff52582d8f1a996d59e6c8ce` passed the GNU source and native-provider controls. The checked-in manifest names every installed file. Of 81 files per role, only the compiler driver and matching rustdoc differ. Both kits expose the same physical strict Cargo 761ea115 and signed -21 Wild. [Source qualification](https://github.com/astral-experiments/ohm/actions/runs/41199659076)

Full ran eight Linux incremental unit tests, Packed ten. Both passed the seven individually selected run-make fixtures. The macOS result applies to the original Full source. The retained Full source job built and reassembled the same 81 files and ran its native compiler tests. A rustdoc diagnostic expectation in that earlier job was wrong. The successful qualification checked the original archives and reran Full's runtime controls, then built Packed from source. The report records both source jobs.

For each compiler, six declared-input provider visits and sixteen warm or independently empty unbundled-provider visits passed. Replacing a same-inode, same-size, same-mtime native archive changed the installed program's value from 29 to 47. Both warm malformed visits and their empty comparisons failed in the real native linker. Repair and removal returned 29 and 17. The receiver verified the selected archive's returned file descriptor through the actual Wild process or an inheriting fork or thread. A separate kernel control opened the same bytes after a different executable took over and was excluded. The offline reader executes the three original native programs per compiler again.

The following commands use the exact Actions ZIPs and run on native x86-64 Linux with Python 3.11 or later and zstd. Each redirected file is a complete ZIP. Read the live Actions metadata from an authorized repository checkout before downloading. GitHub sets a 21-day retention period, and the same replay works offline with original copies.

```sh
D=scripts/branch-return-source
mkdir -p /tmp/ohm-branch-return-reviewed
Z=/tmp/ohm-branch-return-reviewed
python3 -IB "$D/locate.py" 41199659076 caef389ed580829583f1a63df129b7b649e43508 > "$Z/official-live.json"
cmp "$Z/official-live.json" "$D/result/official.json"
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13041858613/zip > "$Z/branch-return-source-sdk.zip"
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13041943456/zip > "$Z/branch-return-source-observations.zip"
python3 -IB "$D/result/reopen.py" "$Z" "$Z/replayed.json"
cmp "$Z/replayed.json" "$D/result/readback.json"
```

The source gate supplies the verified subjects for a separate real Ruff study. It measured no Cargo speed or target storage change.
