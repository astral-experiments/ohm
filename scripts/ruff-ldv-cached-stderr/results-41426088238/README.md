# Cargo diagnostic replay on an unchanged Ruff build

Both independent Linux boots met the registered causal check. Each boot ran the four combinations of runtime mode and cached diagnostic bytes in counterbalanced order, preserving the installed Cargo, target and its 306 cache file inodes. Each command used zero rustcs and zero native linkers. Swapping in the complete recorded candidate diagnostics grew replayed stderr from 63,320 to 145,158 bytes, with 2,750 additional diagnostic-reason lines. At each fixed diagnostic mode the additional cache bytes cost 5,512,623 and 5,198,723 retired user instructions on the first boot and 5,678,046 and 5,251,232 on the second. At fixed bytes, changing only the mode cost between −168,074 and +346,351 instructions (under 0.073%). The earlier signed pilot's 1.183% increase remains its measured result. This supplemental test identifies a removable source of work in that probe.

[Original job and artifacts](https://github.com/astral-experiments/ohm/actions/runs/41426088238)

Reproduce the four fixed-file comparisons from the two independent readbacks.

```sh
p=scripts/ruff-ldv-cached-stderr
python3 -IB "$p/verify.py" both "$p/results-41426088238/boot-1.json" "$p/results-41426088238/boot-2.json" /tmp/ldv-no-codegen-result.json
cmp /tmp/ldv-no-codegen-result.json "$p/results-41426088238/result.json"
```
