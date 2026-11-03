# Both private Ron controls stopped before the treatment

These two jobs revisited the complete signed -24 Ruff #29697 test build in a private namespace. Each job copied and verified 15 regular files onto tmpfs: the signed compiler and its two shared libraries, the proc-macro chosen by the original Ron invocation, nine system libraries, and the two diagnostic components. This cost 1,436,570,944 and 1,437,040,575 retired user instructions. The copies occupied 388,275,472 logical bytes and 388,296,704 allocated bytes on each boot. The diagnostic also compiled a supervisor bound to those actual device/inode generations, costing 10,800,373,706 and 10,800,960,525 instructions respectively.

The first worker refused a kernel per-task counter record with 747,900 enabled and 800,500 running. Its parent Cargo command succeeded, but the counter could not support the enrolled invocation inventory.

On the other boot, Cargo selected the same proc-macro filename in a new shared-output directory on its next ordinary invocation. The original path used shard `v2-a8fbe94e456541b1`; the new argv selected `v2-7593acb9423336de`. The latter executable mapping had overlay device 0:32 while the descriptor reopened by its pathname had device 0:33. The other 12 product and operating-system mappings passed physical generation comparison. The enrolled code stopped before opening a Ron timing window. Neither worker produced a treatment cost or a whole-Cargo speedup.

`original-records.zip` retains the full staged physical bills, mapping inventories, original kernel counts and the real NUL-delimited Ron invocations. Run the offline reader from this directory. With the two original GitHub worker ZIPs named PC.zip and CP.zip, the second command verifies every byte against the original artifact digest as well.

```sh
python3 -IB reopen.py
python3 -IB reopen.py --originals /path/to/two-originals
```

[Original attempted workers](https://github.com/astral-experiments/ohm/actions/runs/41728731915) · [Ordinary published -24 workload and filesystem guard](https://github.com/astral-experiments/ohm/blob/cac703977b69c50d130639cf0bd9cbe86e28619d/scripts/ron-native-platform-24/README.md).
