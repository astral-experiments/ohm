# Private-derive compiler and Cargo compatibility

This unscored Linux qualification exercised 314 ordinary Cargo commands. The source worktree and target stayed at fixed paths within each migration. P2 is d46c44b5 (#347), Q2 is its experimental private-derive child b6c3da0e, and both use the v5 #436 reader with the c1d1c6c8 handshake. The actual signed -23 Cargo, the earlier private v1 client/writer and the v5 reader without the handshake supply mixed-version controls. Physical tool sizes and SHA-256 digests are in `local-physical.json`.

- Three 40-command histories read the provider's genuine emitted .rmeta through `include_bytes!`. They include valid private edits, normal repair, independently empty E0308, the signed client and the enrolled Cargo-home registry output layout.
- Four 44-command real upgrade, downgrade and switching histories include both directions with both enabled interfaces, cancelled probes, regular check-to-build, defaults-off, a workspace wrapper and independent clean ELF output. The reviewer reopens the kernel exec and driver mappings, compiler argv, selected physical outputs, public headers and artifact identities.
- Eighteen additional commands ran conflicting and agreeing reads of two lexical names for the same file, on each current compiler. The first unchanged and independently empty check both rejected inconsistent inputs with E0308. Agreed inputs remained fresh. Native repaired and empty programs both printed `29 29`. For the alias binaries the original captures contain the executing ELF digest and the observed verdict. The separate parked histories retain the physical native ELF bytes.

Run from this directory with Python 3, zstd and b3sum installed:

```sh
python3 -IB verify.py current.zip prior.zip --b3sum "$(command -v b3sum)" --out /tmp/derive-reopened.json
cmp /tmp/derive-reopened.json reopened.json
```

The earlier two acquisitions remain distinct. The first was refused before a subject command. The second ran 80 commands then its outdated decoder refused v5. The corrected reader consumes those original bytes, and the final worker references them once. The two archive SHA-256 values, every raw member, and 314 distinct commands are checked before the final summary is written. All counts are correctness controls.

[Original refused input enrollment](https://github.com/astral-experiments/ohm/actions/runs/41611476135) · [Original 80 commands](https://github.com/astral-experiments/ohm/actions/runs/41612088857) · [Final acquisition](https://github.com/astral-experiments/ohm/actions/runs/41613048377)
