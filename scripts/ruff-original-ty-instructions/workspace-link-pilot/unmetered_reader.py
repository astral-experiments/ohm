"""Exact ordinary source/ELF enrollment on the dedicated -24 safety worker."""

import re
from pathlib import Path

HEAD = "31b89aefc9a96e9ec7d340cf990e3ada0e5644ef"
RUN = 41747172339
MODES = {
    "earlier": "earlier",
    "four": "four",
    "malformed": "malformed",
    "mid-read": "save",
}


def plans(members):
    """Recreate the fixed order, admitting only the predeclared bounded retries."""
    seen = {
        s[: -len("-receipt.json.gz")]
        for s in members
        if re.fullmatch(r"[PC]-[^/]+-receipt\.json\.gz", s)
    }
    names = []
    for arm in ("P", "C"):
        if arm == "C":
            names.append("C-empty-new")
        names += [
            arm + "-" + s
            for s in (
                "old",
                "edit",
                "warm1",
                "ordinary-repeat-old",
                "ordinary-repeat-edit",
            )
        ]
        if arm == "P":
            names.append("P-empty-new")

    def observed(base, start=1, first_unsuffixed=False):
        found = []
        for n in range(start, 7):
            tag = base if n == 1 and first_unsuffixed else base + "-" + str(n)
            if tag in seen:
                assert n == start + len(found)
                found.append(tag)
        return found

    for mode, suffix in MODES.items():
        names += observed("C-before-native-" + mode)
        names += ["C-native-" + suffix, "C-native-" + suffix + "-repair"]
    preparation = observed("C-before-output-control")
    names += preparation
    names += observed("C-distinct-OPATHs", first_unsuffixed=True)
    for i, phase in enumerate(
        observed("C-actual-output-repair", first_unsuffixed=True), 1
    ):
        names.append(phase)
        names += observed("C-train-output-repair-" + str(i))
    names += ["C-actual-type-error", "C-actual-type-repair"]
    assert len(names) == len(set(names)) and seen <= set(names), seen - set(names)
    return names, [int(t.rsplit("-", 1)[1]) for t in preparation[2:]]


def before_native(j, phases, tag, role):
    mode = next(key for key, val in MODES.items() if tag == "C-native-" + val)
    selected = j("selected-before-native-" + mode + ".json")
    key = selected["phase"]
    earlier = [k for k in phases if k.startswith("C-before-native-" + mode + "-")]
    assert 1 <= len(earlier) <= 6 and key == earlier[-1]
    for k in earlier:
        actor = j(k + "/physical-decisions.json")["actors"][role]
        assert bool(actor.get("physical") and actor["allowed"]) == (k == key)
    assert selected == {"phase": key, "sha256": phases[key]["elfs"][role][0]}
    return selected["sha256"]


def resources(j, members, tag, row):
    assert "meter" not in row and not any(
        x.startswith(tag + "/tasks/")
        or x in (tag + "/hardware.json", tag + "/owner-census.json.gz")
        for x in members
    )
    r = j(tag + "/resources.json")
    assert (
        r["exit"] == row["exit"]
        and r["minimum_mem"] >= 8 << 30
        and r["minimum_disk"] >= 15 << 30
    )
    assert r["seconds"] > 0


def second_edit(j, data, phases, subset, members, complete):
    if "ordinary-second-edit-and-empty.json" not in members:
        assert not complete
        return None
    reference = phases["P-empty-new"]["elfs"]
    actual = {
        "certified_second_edit_hits": sorted(
            phases["C-ordinary-repeat-edit"]["native"]["fresh"]
        )
    }
    for k, tag in (
        ("P_second_vs_signed_empty", "P-ordinary-repeat-edit"),
        ("C_second_vs_signed_empty", "C-ordinary-repeat-edit"),
        ("C_independent_empty_vs_signed_empty", "C-empty-new"),
    ):
        r = phases[tag]["elfs"]
        assert set(r) == set(reference) and len(r) == 50
        actual[k] = {role: r[role] == value for role, value in reference.items()}
    assert actual == j("ordinary-second-edit-and-empty.json")
    for arm in ("P", "C"):
        for stage in ("-withheld-old-on-new", "-withheld-ordinary-repeat-old"):
            raw = data(arm + stage + "/stdout")
            assert all(n in raw for n in (b"1 failed;", b"script_tag", b"source_text"))
        inv = j(arm + "-empty-new/inventory.json.gz")
        assert len(inv["units"]) == 623 and not any(fresh for _, fresh in inv["units"])
        assert len(inv["executables"]) == 102
        for stage in (
            "old",
            "edit",
            "warm1",
            "ordinary-repeat-old",
            "ordinary-repeat-edit",
            "empty-new",
        ):
            native = data(arm + "-" + stage + "-native/stdout")
            assert b"1 passed;" in native
    for phase in ("C-empty-new", "C-old"):
        r = j(phase + "/physical-decisions.json")
        assert r["before_bytes"] == 0 and not phases[phase]["native"]["fresh"]
    return {
        **actual,
        "certified_hit_matches_clean": all(
            actual["C_second_vs_signed_empty"][role]
            for role in actual["certified_second_edit_hits"]
        ),
        "unexpected_signed_or_candidate_roles": {
            key: sorted(role for role in subset if not actual[key][role])
            for key in actual
            if key != "certified_second_edit_hits"
        },
    }


def output_controls(j, phases, roles, e2e):
    """Reopen every physically attempted corruption and both real O_PATH generations."""
    targets = set(j("before-output-selection.json")["targets"])
    assert targets <= set(roles) and len(targets) == 2 and e2e in targets
    selected = j("actual-canonical-OPATHs-stage.json")["phase"]
    earlier = [k for k in phases if k.startswith("C-distinct-OPATHs")]
    assert earlier and selected == earlier[-1]
    for k in earlier:
        assert (targets <= set(phases[k]["native"]["fresh"])) == (k == selected)
    done = j("actual-output-repair-stage.json")
    assert done["targets"] == sorted(targets)
    repairs = [k for k in phases if k.startswith("C-actual-output-repair")]
    assert repairs and repairs[-1] == done["phase"]
    for i, k in enumerate(repairs, 1):
        actions = j(k + "/physical-decisions.json")["actors"]
        proved = set()
        for role in targets:
            r = actions[role]
            f = j(
                "corrupted-existing-"
                + Path(role).name
                + ("" if i == 1 else "-" + str(i))
                + ".json"
            )
            digest, size = phases[k]["elfs"][role]
            assert (
                f["inverse_full_sha256"] == digest != f["sha256"] and f["bytes"] == size
            )
            assert (
                0 <= f["text_offset"] < size and f["byte_before"] ^ f["byte_after"] == 1
            )
            assert r["action"] in ("full", "full-typed-refusal")
            if (
                r["response"] == "verify"
                and r["action"] == "full"
                and "output-bytes-or-generation" in r["reasons"]
            ):
                proved.add(role)
        assert (targets == proved) == (k == repairs[-1])
    return selected, repairs[-1]
