# Full native execution after an earlier library was selected

Two research runs exercised the real Ruff #29697 edit and ordinary virtual-workspace test build on signed Linux releases -23 and -24. Both stopped at a QA assertion about the native linker's action. Each preserved the physical inputs, complete native emission, Ruff inventories, counters, and the failed assertion. Independent empty NEW and later repair had yet to run. These are one-boot discovery counts.

## The two native challenges

Both Wild processes selected, opened, froze, and consumed the same 1,094-byte archive from rustc's temporary `raw-dylibs/libutil.a`. The independent reader rebuilds its single `guard.o` with GNU as and ar, checks both full content hashes, then binds that buffer to the actual lookup and open by path, device, inode, length, and owning process. The archive defines `zzQA` and a constructor that performs Linux `exit_group(83)`.

* On -23, changing four symbol-table bytes at offsets 8731–8734 in the genuine 39,760-byte `symbols.o` replaced `main` with `zzQA`. Wild emitted a 227,979,400-byte executable with SHA-256 `8c579fff30074179355f18b92e83ef24ba7649894dfd6b456f11fe306873eeb6`. The previous 227,979,336-byte executable had SHA-256 `86b94323a752a316a501f542a846408648ca8b74c56bc60298690b671b7b0563`. The QA assertion stopped execution before the new binary's expected exit 83 could be checked.
* On -24, adding just that earlier archive left the genuine 40,024-byte `symbols.o` unchanged. Wild emitted the same complete 226,598,344-byte executable as the preceding normal NEW link, SHA-256 `9827cae719308452d3293caadd022351e4a940b9c01502c3da339d12c036ed25`. Its real Ruff test `commands::debug_command` passed with 199 other tests filtered out.

Both returned the coordinator response `full`, executed the actual projected group, and emitted a full executable. Both deliberately withheld a subsequent donor receipt, since the additional input fell outside the registered domain. The earlier QA assertion expected a subsequently reusable full output. The replacement checks the changed input bytes, full output, admission refusal, real native execution, clean symbol/ELF relation and actual runtime separately. Its offline negative mutations reject forged hits, missing emissions, wrong open generations and wrong input or output digests.

A separate first-attempt single-target study executed the *same complete changed ELF* under `--list` and recorded exit 83 with empty stdout. Its raw output BLAKE3 and SHA-256, byte length, both selected native buffers and four changed offsets all match this -23 workspace challenge. The dedicated reader joins the two original archives and reproduces `cross-run-exit.json`. Later workspace trials still require their own observed exit 83. [Independent actual execution](https://github.com/astral-experiments/ohm/actions/runs/41723091119) · [Command and return-code check](https://github.com/astral-experiments/ohm/blob/575582bd4f55f4410720e31ef04261b8238b8042/scripts/ruff-original-ty-instructions/e2e-existing-output/audit.py#L252)

~~~sh
python3 -IB verify_prior_exit.py functional-4-original.zip release23-41737649726.zip > cross-run-reproduced.json
cmp cross-run-exit.json cross-run-reproduced.json
~~~

## Whole unchanged command

| Signed release | Native outputs reused (of 50) | P ordinary instructions, billions | Research C ordinary instructions, billions | P → C elapsed seconds |
| --- | --- | --- | --- | --- |
| -23 | 48, 48, 48 | 80.009, 80.007, 80.005 | 63.188, 63.026, 63.168 | 5.93→5.98, 5.90→5.84, 6.12→6.19 |
| -24 | 46, 46, 47 | 124.090, 124.077, 124.103 | 113.047, 113.152, 111.076 | 7.51→8.67, 7.51→8.71, 8.14→9.40 |

Both arms use ordinary Cargo with the same flags. Each source-linker call reacquires every actual native operand and verifies the previous ELF before making a fresh output inode. The earlier two strict role exclusions remain. The C histories retain 13–14 KB in an anonymous receipt file between commands. The independent post-warm scans found zero other files with any of these 50 complete ELF digests in either arm. During individual C writes, the previously named inode can remain held. Summed over the 48 enrolled outputs, this accounted for 3.58 GB of previously allocated output on -23 and 3.19–3.34 GB on -24 per warm command. This sum does not measure peak resident disk or RAM.

The first genuine edit cost 284.763B→329.123B (-23) and 219.340B→263.700B (-24). The edit plus its next unchanged build cost 7.55% more on -23 and 9.70% more on -24 in these discovery runs. An unchanged command reread 12.225 GB of native input on -23 and 12.184 GB on -24. The -24 whole build includes three full compilers as well as 50 rustc link-only commands and all 50 native links.

The independent kernel census prices the eligible stock links together at 58.467B of 80.015B on -23. The maximum allowed proof cost for a 2× command at that baseline is 18.460B. On -24 the same 48 links cost 58.171B out of 124.080B. Even removing all their original instructions leaves 65.909B and a maximum 1.883×. The count includes a 2.548B difference between the outer event and traced image subtotals, which remains unattributed. Another traced C call changed the inherited jobserver-FD spelling held by `CARGO_MAKEFLAGS` and changed the stored context on all 48 roles on both hosts. Its full native executions cannot price an ordinary unchanged hit.

On the first unchanged call, the kernel accounted for 0.615→17.146 GB of read-system-call bytes and 3.915→3.986 GB of disk writes on -23, and 0.638→16.967 GB of read-system-call bytes and 3.954→3.866 GB of disk writes on -24. The toolchain's stock mmap and the research path's explicit reads charge the former counter differently. Actual storage read bytes were zero across these four runs on the warm cache. On -24 the independent signed full-compiler counts were 41.644B for `insta`, 2.586B for `insta_cmd`, and 9.328B for `ron`.

Signed -23's own last ordinary warm and traced warm e2e executables differed at equal size. Of 42 recorded sections, only the 48-byte GNU build-ID payload changed. The complete ordinary hash begins `86b94323` and the separate traced hash begins `d236bd03`. The archive preserved complete-file digests and section hashes, so this observation does not cover unrecorded ELF header fields or padding. The -24 signed warm and traced comparison matched all 50 raw executable digests.

## Reopen

Download the two original Actions ZIP archives and use a GNU x86-64 host with Python, GNU as/ar/objdump, and the signed kit's LLVM BLAKE3 API. The reader checks the complete archive hashes and opens the original native streams, compiler inventories, GNU hardware clocks and signed native process epochs. Output must compare byte-for-byte with `originals.json`.

~~~sh
python3 -IB verify.py release23-41737649726.zip release24-41737656295.zip \
  /path/to/signed-sdk/lib/libLLVM.so.23.1-rust-1.99.0-beta > reproduced.json
cmp originals.json reproduced.json
~~~

* [Signed -23 first-attempt run](https://github.com/astral-experiments/ohm/actions/runs/41737649726), artifact 13279449314, 41,514,240 bytes, SHA-256 `b793f66dcaa3d935abca0fc2d5d9fd6de9737da7c3e3c1b05836581ffe481c7f`.
* [Signed -24 first-attempt run](https://github.com/astral-experiments/ohm/actions/runs/41737656295), artifact 13280727843, 41,550,228 bytes, SHA-256 `cd34338da0ad5cb2812ac7f87baea7f93d97e49196ac448fb82cc0a7781d5505`.
