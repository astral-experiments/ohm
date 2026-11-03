# Independent signed instruction attribution

The native admissibility and identity rules are frozen in 9ec1f2f6. This supplementary reader was prepared before opening the new 50-role native outputs. It reopens the original NUL argv, image identities, matching PID parent/child fork, typed unit, full output SHA and unscaled per-TID counter deltas for every role on two separately recorded signed workspace runs.

| Signed original | Inherited whole command | All assigned epochs | 50 named Wild invocations with their fork-inherited workers | Outer minus all assigned |
| --- | ---: | ---: | ---: | ---: |
| [41617756983](https://github.com/astral-experiments/ohm/actions/runs/41617756983) | 80,011,869,840 | 76,176,133,768 | 62,931,726,553 | 3,835,736,072 |
| [41627259427](https://github.com/astral-experiments/ohm/actions/runs/41627259427) | 80,010,035,283 | 80,010,037,434 | 66,762,571,144 | −2,151 |

The 14 largest *assigned* native roles are required on either worker to reach half the observed total, even if their entire cost disappeared. On the first worker, assigning every missing instruction to an eligible native role would lower that minimum to 13. The complete command totals differ by 0.0023%.

Two per-role prices differed by more than 2% of the smaller count. Both named ELF files had the exact same SHA on the two workers. The ty_python_semantic library test had 5,182,805 against 2,844,852,624 attached instructions. ty_module_resolver had 4,004,645 against 1,000,152,683. Their combined difference of 3,835,817,857 accounts for almost the entire earlier underassignment. Forty-seven of the 50 full named outputs match across workers. The three differing SHA owners are the ruff binary, ruff_server library test, and ty binary, separate from the two counter outliers.

For each accepted subset, the supplemental reader reports each signed worker's independently observed instruction weight and a generous bound that adds the first worker's entire positive residual. It makes no cost or speed assumption for a proposed implementation. An observed small cohort cannot veto the objective when the conservative bound or independently counted worker still allows it.

    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13223081435/zip > original-a.zip
    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13226747746/zip > original-b.zip
    python3 -IB independent_role_bounds.py original-a.zip original-b.zip | cmp - two-signed-hardware.json
    python3 -IB coverage_ceiling.py complete-native-readback.json
