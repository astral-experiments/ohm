"""Compute the pre-enrolled summaries from each arm's contiguous untraced history."""

PHASES = ("Y-B", "X-A", "X-B", "comment", "unchanged", "invalid", "repair")


def count(clocks):
    if tuple(clocks) != PHASES:
        raise ValueError("missing or reordered ordinary Cargo phase")
    rows = {}
    previous = 0
    for phase, raw in clocks.items():
        insn, start, stop, code = (
            raw[k] for k in ("instructions", "start", "stop", "code")
        )
        if not (
            all(type(v) is int for v in raw.values())
            and raw["event_errno"] == 0
            and raw["running"] == raw["enabled"] > 0
            and raw["user_us"] + raw["system_us"] > 0
            and insn > 0
            and previous < start < stop
            and code == (101 if phase == "invalid" else 0)
        ):
            raise ValueError(
                "invalid foreground Cargo counter, result or monotonic interval"
            )
        previous = stop
        rows[phase] = dict(
            instructions=insn,
            elapsed_ns=stop - start,
            start=start,
            stop=stop,
            status=code,
        )

    def total(phases):
        return {
            k: sum(rows[p][k] for p in phases) for k in ("instructions", "elapsed_ns")
        }

    return dict(
        phases=rows,
        whole7=total(PHASES),
        comment_plus_unchanged=total(("comment", "unchanged")),
        failed=total(("invalid",)),
        repair=total(("repair",)),
    )
