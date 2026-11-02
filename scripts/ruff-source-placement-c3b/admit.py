"""Run the original unscored two-role Ruff histories with the newly built C3b kit."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import footer
import scope
import worker as prior


def main():
    slot = int(sys.argv[1])
    sources = {
        name: Path(v).resolve(strict=True)
        for name, v in zip(("option", "e2e"), sys.argv[2:], strict=True)
    }
    study = scope.bind()
    scope.base.need(study["native"]["no_PMU"] and slot in (1, 2), "unregistered native probe")
    with scope.product("C3b") as reg, ExitStack() as stack:
        # The matched Cargo entry, native observer and all four integrity histories
        # are exactly the previously audited source. Only the new physical kit and
        # its versioned wire have changed.
        stack.enter_context(patch.object(prior, "enrollment", lambda: reg))
        stack.enter_context(patch.object(prior.transport, "BRANCH", scope.BRANCH))
        stack.enter_context(patch.object(prior.receiver, "FACTORY", scope.C3_FACTORY))
        stack.enter_context(patch.object(prior.storage, "parse_footer", footer.parse))
        scope.base.need(
            prior.runtime.transport.capsule is scope.base.capsule,
            "two different native SDK receivers",
        )
        prior.collect("admit", slot, sources)
    _, evidence, _ = prior.census.paths()
    p = evidence / "physical"
    entry = json.loads((p / "entry.json").read_bytes())
    scope.base.save(
        p / "directional-gate.json",
        {
            "schema": "C3b-two-native-1",
            "slot": slot,
            "previous_operator": scope.base.sha(scope.ORIGINAL / "protocol.json"),
            "prospective": scope.base.sha(scope.HERE / "three-arm-protocol.json"),
            "packet": scope.base.sha(scope.HERE / "source-packet.json"),
            "complete": scope.base.sha(p / "complete.json"),
            "actual_factory": entry["factory"],
            "source": entry["source"],
            "boot": entry["boot"],
        },
    )


if __name__ == "__main__":
    main()
