"""Reopen the original native lookup, byte, publisher, Cargo and Linux counter records."""

from collections import Counter
import gzip, hashlib, json, re, sys
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "workspace-link-proof")]
import coordinator, native_fallback, release_scope, unmetered_reader

E2E = "/ty_server/f5c6198f896cf7b0/out/e2e-f5c6198f896cf7b0"


def wild_argv(body, row):
    """Authenticate a physical Wild exec and its single literal GNU output operand."""
    fields = body.split(b"\0")
    args = fields[4:-1]
    assert bytes_for(body) == row["argv_sha256"] and fields[-1] == b""
    assert list(map(int, fields[:3])) == [row["pid"], row["dev"], row["ino"]]
    assert fields[3] == args[0] and fields[3].decode() == row["path"]
    assert args.count(b"-o") == 1
    assert args[args.index(b"-o") + 1].decode() == row["output"]
    return fields


def fresh_generation(op, old, physical):
    (accept,) = op["ACCEPT"]
    (f,) = op["FRESH-GENERATIONS"]
    d, i, n, blocks, links, writerdev, writerino, nameddev, namedino = map(int, f)
    assert (
        [int(x) for x in accept[:3]]
        == [d, i, n]
        == [old["dev"], old["ino"], old["size"]]
    )
    assert accept[3] == old["output"] == physical["output"]
    assert int(op["FRESH-PUBLISH"][0][0]) == n == physical["size"]
    assert (
        blocks > 0
        and links == 0
        and (d, i)
        != (writerdev, writerino)
        == (nameddev, namedino)
        == (physical["dev"], physical["ino"])
    )
    return 512 * blocks


def bytes_for(data):
    return hashlib.sha256(data).hexdigest()


def selected_elfs(inv, specs):
    result = {}
    for name, row in inv["executables"].items():
        assert row["elf"]["bytes"] > 0 and re.fullmatch(
            r"[0-9a-f]{64}", row["elf"]["sha256"]
        )
        for k in specs:
            if name.endswith(k):
                assert k not in result and row["unit"] == specs[k]["owner"]
                result[k] = (row["elf"]["sha256"], row["elf"]["bytes"])
    assert len(result) == 50 and len(inv["executables"]) == 102
    return result


def intake(path, expected_sha, head, run, release):
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected_sha
    z = ZipFile(path)
    members = set(z.namelist())
    assert len(members) == len(z.namelist())

    def data(n):
        body = z.read(n)
        return gzip.decompress(body) if n.endswith(".gz") else body

    j = lambda n: json.loads(data(n))
    enroll = j("admission.json")
    assert (
        enroll["head"] == head
        and enroll["run"] == str(run)
        and enroll["release"] == release
    )
    assert re.fullmatch(r"[0-9a-f-]{36}", enroll["boot"])
    assert enroll["Ruff"] == [
        "157caa55a51ebae4fa541d31697e3af9a6c32ccf",
        "bfa2407e98ee1343caeefd02b4b69043509baa8c",
    ]
    plain = enroll.get("kind") == "unmetered-native-safety-v1"
    assert plain == (head == unmetered_reader.HEAD)
    if plain:
        assert release == 24 and int(run) == unmetered_reader.RUN
        assert "meter-calibration.json" not in members
        assert not any(
            n.endswith("/hardware.json")
            or "/tasks/" in n
            or n.endswith("/owner-census.json.gz")
            for n in members
        )
    full = release_scope.for_release(release)
    subset = set(enroll["roles"])
    spec = {k: full[k] for k in subset}
    assert len(subset) == 48 and subset == set(
        json.loads((HERE / "accepted-48.json").read_bytes())
    )
    setup = j("physical.json")
    actor = j("actor.json")
    assert (
        actor["actor"] == setup["actor"]
        and setup["stock"]
        == actor["stock"]
        == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
    )
    assert actor["source"] == enroll["source_registration"]["after"]
    assert actor["source_pin"] == "e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11"
    if not plain:
        calibrate = j("meter-calibration.json")
        assert (
            calibrate["instructions"] > 0
            and calibrate["enabled"] == calibrate["running"] > 0
            and calibrate["reaped"] == 2
        )
        assert (
            calibrate["write_bytes"] >= 6291456
            and calibrate["wchar"] >= 6291456
            and calibrate["rchar"] >= 6291456
        )
        assert calibrate["system_us"] > 0 and calibrate["outblock"] >= 12288
    ledger = {}
    prior_bytes = 0
    phases = {}
    refusal = {}
    list_sha = None
    complement = {}
    strong_native = plain or head in {
        "d68c5ce147ce6089d48f2524836ab663737c175f",
        "db84fc8eed1057088d9c186cdb06ee839ce8fde0",
    }
    guarded_outputs = {}
    initial = (
        "old",
        "edit",
        "warm1",
        "warm2",
        "warm3",
        "exec-warm",
        *(
            ("exec-warm-stable", "ordinary-repeat-old", "ordinary-repeat-edit")
            if strong_native
            else ()
        ),
        "reverse-old",
        "exec-edit",
    )
    names = [a + "-" + s for a in ("P", "C") for s in initial]
    for mode in (["earlier"] if release == 24 else []) + ["four", "malformed", "save"]:
        names += ["C-native-" + mode, "C-native-" + mode + "-repair"]
    names += ["C-before-output-control-1", "C-before-output-control-2"]
    extra = [
        i
        for i in range(3, 7)
        if f"C-before-output-control-{i}-receipt.json.gz" in members
    ]
    assert extra == list(range(3, 3 + len(extra))) and (not extra or strong_native)
    names += [f"C-before-output-control-{i}" for i in extra]

    if release == 24:
        names += ["C-distinct-OPATHs"]
    names += [
        "C-actual-output-repair",
        "C-actual-type-error",
        "C-actual-type-repair",
        "P-empty-new",
        "C-empty-new",
    ]
    if plain:
        names, extra = unmetered_reader.plans(members)
    for tag in names:
        if tag + "-receipt.json.gz" not in members:
            continue
        row = j(tag + "-receipt.json.gz")
        code = row["exit"]
        prefix = tag + "/"
        assert code == (
            101
            if tag in ("C-native-malformed", "C-native-save", "C-actual-type-error")
            else 0
        )
        out = [json.loads(line) for line in data(prefix + "stdout.jsonl").splitlines()]
        assert out[-1] == {"reason": "build-finished", "success": code == 0}
        record = {"code": code, "source": row["state"]}
        if plain:
            unmetered_reader.resources(j, members, tag, row)
        if prefix + "hardware.json" in members:
            m = j(prefix + "hardware.json")
            assert m == row["meter"] and m["instructions"] > 0
            assert (
                m["running"] == m["enabled"] > 0
                and m["status"] == 256 * code
                and m["user_us"] > 0
                and m["system_us"] > 0
            )
            record["meter"] = m
        elif not plain:
            assert "exec-" in tag
            e = j(prefix + "owner-census.json.gz")
            actual = [r for r in e["roles"] if r["trigger"] == "exec"]
            wild = [r for r in actual if r["mode"] == "Wild"]
            names_out = [k for r in wild for k in full if r["output"].endswith(k)]
            assert len(names_out) == len(set(names_out)) == 50
            original = [
                r for r in actual if r["path"].endswith("/qa-diagnostic-build/original")
            ]
            others = {}
            enrolled = {r["epoch"]: r for r in e["roles"]}
            for r in wild:
                body = data(prefix + "tasks/" + r["argv"])
                fields = wild_argv(body, r)
                if not any(r["output"].endswith(k) for k in full):
                    owner = enrolled[r["owning_rustc_epoch"]]
                    assert owner["trigger"] == "exec" and owner["mode"] in (
                        "full",
                        "test",
                        "link-only",
                    )
                    assert r["output"] not in others
                    others[r["output"]] = [
                        owner["mode"],
                        owner["crate"],
                        r["argv_sha256"],
                    ]
                redirect = [
                    x
                    for x in original
                    if x["pid"] == r["pid"] and x["epoch"] > r["epoch"]
                ]
                if tag.startswith("C-") and not any(
                    r["output"].endswith(k) for k in subset
                ):
                    (extra,) = redirect
                    again = data(prefix + "tasks/" + extra["argv"])
                    second = again.split(b"\0")
                    assert (
                        bytes_for(again) == extra["argv_sha256"]
                        and second[4:] == fields[4:]
                    )
                    assert list(map(int, second[:3])) == [
                        extra["pid"],
                        extra["dev"],
                        extra["ino"],
                    ]
                    assert second[3].decode() == extra["path"] and (
                        r["dev"],
                        r["ino"],
                    ) != (extra["dev"], extra["ino"])
                else:
                    assert not redirect
            assert len(original) == (
                len(wild) - len(subset) if tag.startswith("C-") else 0
            )
            record["other_native_full"] = others
            record["physical_execs"] = e["real_execs"]
        if not code:
            inv = j(prefix + "inventory.json.gz")
            assert inv["state"] == record["source"] and len(inv["units"]) > 500
            elfs = selected_elfs(inv, full)
            assert {k: v for k, (v, n) in elfs.items()} == row["published"]
            record["elfs"] = elfs
            if tag != "C-native-four" and tag + "-native/test-list" in members:
                test = data(tag + "-native/test-list")
                digest = bytes_for(test)
                assert (
                    len([l for l in test.splitlines() if l.endswith(b": test")]) == 200
                )
                assert list_sha in (None, digest) and b"1 passed;" in data(
                    tag + "-native/stdout"
                )
                list_sha = digest
            if (
                strong_native
                and tag in ("C-native-four", "C-native-earlier")
                and tag + "-full-output.json" in members
            ):
                received = j(tag + "-full-output.json")
                actor = j(prefix + "physical-decisions.json")["actors"][E2E]
                native_raw = data(prefix + "actor-" + actor["pid"] + ".tsv.gz").decode()
                # Exact bytes from independently rebuilt guard.o member in libutil.a.
                provider = {
                    "bytes": 1094,
                    "sha256": "a83083cb94eedabc22eb859b71a97adf67b48f6860849d958d1e0ad028b7a273",
                    "blake3": "6155742e854e1274d63647f3d0137dd6fa9cabaefb4ab9c23e8a8bf6eeb4510c",
                }
                actual = received["actual_output"]
                assert actual["path"].endswith("/" + inv["binary"])
                assert elfs[E2E] == (actual["sha256"], actual["identity"][2])
                assert received == native_fallback.check(
                    actor,
                    native_raw,
                    j(tag + "-actual-change.json"),
                    provider,
                    actual,
                    (
                        unmetered_reader.before_native(j, phases, tag, E2E)
                        if plain
                        else phases["C-exec-edit"]["elfs"][E2E][0]
                    ),
                )
                guarded_outputs[tag] = received
        if tag.startswith("C-"):
            if tag == "C-empty-new" or (plain and tag == "C-old"):
                ledger = {}
                prior_bytes = 0
            answer = j(prefix + "physical-decisions.json")
            assert answer["exit"] == code and answer["commit"] == (code == 0)
            assert answer["before_bytes"] == prior_bytes
            assert 0 <= answer["after_bytes"] <= 64 << 10
            orig = {
                x[len(prefix + "actor-") : -len(".tsv.gz")]: x
                for x in members
                if x.startswith(prefix + "actor-") and x.endswith(".tsv.gz")
            }
            assert len(orig) == row["source_role_logs"]
            if not code:
                assert (
                    len(orig) == 48
                    and len(answer["actors"]) + len(answer["proof_refusals"]) == 48
                )
            issued = {}
            next_ledger = {}
            total_input = 0
            actual_write = 0
            held = 0
            all_threads = Counter()
            parsed_bytes = 0
            for role, rec in answer["actors"].items():
                chunk = data(orig[rec["pid"]]).decode()
                op = coordinator.rows(chunk)
                pre = coordinator.before(chunk, spec, setup["image_b3"])
                assert (
                    pre["role"] == role
                    and pre["key"] == rec["key"]
                    and rec["parts"] == pre["parts"]
                    and rec["prior"] == ledger.get(role)
                )
                previous = ledger.get(role)
                if rec["response"] == "verify":
                    assert previous and previous["key"] == pre["key"] and pre["allowed"]
                else:
                    assert rec["response"] == "full"
                if code:
                    continue
                (emitted,) = op["EMITTED"]
                assert op["VERIFIED"] == [[]]
                d, i, n, h, where = emitted
                assert (
                    where == pre["path"]
                    and where.endswith(role)
                    and int(n) == record["elfs"][role][1]
                )
                physical = {"dev": int(d), "ino": int(i), "size": int(n), "output": h}
                total_input += pre["input_bytes"]
                actual_write += int(n)
                (typed,) = op["TYPED"]
                all_threads[int(typed[4])] += 1
                if op["FRESH-PUBLISH"]:
                    assert (
                        len(op["FRESH-PUBLISH"]) == 1
                        and not op["ACTUAL-GROUP"]
                        and int(typed[4]) == 1
                    )
                    assert (
                        rec["response"] == "verify"
                        and rec["action"] == "fresh"
                        and previous
                    )
                    held += fresh_generation(op, previous, physical)
                    origin = previous["full_stage"]
                    issued[role] = int(n)
                else:
                    assert op["ACTUAL-GROUP"] == op["PROJECTED-GROUP"] and rec[
                        "action"
                    ].startswith("full")
                    if not pre["allowed"]:
                        assert rec["action"] == "full-typed-refusal"
                        continue
                    origin = tag
                    parsed_bytes += int(n)
                assert rec["physical"] == physical and rec["from_full_stage"] == origin
                next_ledger[role] = {
                    **physical,
                    "key": pre["key"],
                    "full_stage": origin,
                }
            if not code:
                assert (
                    set(issued) == set(row["fresh_roles"])
                    and held == row["held_allocated"]
                    and total_input == row["native_bytes_consumed"]
                )
                assert parsed_bytes == row["signed_output_reads_for_donor"]
                ledger = next_ledger
                prior_bytes = len(coordinator.encode(ledger)) + 32
                assert answer["after_bytes"] == prior_bytes
                record["native"] = {
                    "full_physical": len(orig) - len(issued),
                    "fresh": issued,
                    "held_output_allocation": held,
                    "source_input_bytes": total_input,
                    "source_read_after_full_donor": parsed_bytes,
                    "output_bytes": actual_write,
                    "workers": dict(all_threads),
                    "receipt_memory_bytes": answer["after_bytes"],
                    "pure_fallback_paths": answer["proof_refusals"],
                }
            else:
                assert answer["after_bytes"] == prior_bytes
                e2e = []
                for x in orig.values():
                    raw = data(x).decode()
                    if E2E in raw:
                        e2e.append(raw)
                if tag != "C-actual-type-error":
                    assert (
                        len(e2e) == 1
                        and "FRESH-PUBLISH\t" not in e2e[0]
                        and "\nVERIFIED\n" not in e2e[0]
                    )
                if tag == "C-native-save":
                    assert "\nREFUSED\tchanged-during-read\t" in e2e[0]
                if tag == "C-actual-type-error":
                    assert b"E0308" in data(prefix + "stdout.jsonl") + data(
                        prefix + "stderr"
                    )
        phases[tag] = record
    timed = {
        k: {
            "instructions": v["meter"]["instructions"],
            "user_us": v["meter"]["user_us"],
            "system_us": v["meter"]["system_us"],
            "elapsed_ns": v["meter"]["elapsed_ns"],
            "rchar": v["meter"]["rchar"],
            "wchar": v["meter"]["wchar"],
            "read_bytes": v["meter"]["read_bytes"],
            "write_bytes": v["meter"]["write_bytes"],
        }
        for k, v in phases.items()
        if "meter" in v
    }
    ordinary = (
        unmetered_reader.second_edit(
            j, data, phases, subset, members, "complete.json" in members
        )
        if plain
        else None
    )
    accepted = False
    if "complete.json" in members:
        assert len(phases) == len(names)
        for tag, r in phases.items():
            if "elfs" not in r or tag == "C-native-four":
                continue
            comp = phases["P-old" if tag.endswith("-old") else "P-empty-new"]
            bad = [k for k in full if r["elfs"][k] != comp["elfs"][k]]
            if bad:
                complement[tag] = bad
            if tag.startswith("C-") and subset & set(bad):
                refusal[tag] = sorted(subset & set(bad))
        expected = j("complete.json")
        # Report even real full fallbacks that differ from the signed clean output.
        # The producer's compact failing row prefers changed hits if there were any.
        projected_failures = {
            k: sorted(set(v) & phases[k]["native"]["fresh"].keys()) or sorted(v)
            for k, v in refusal.items()
        }
        assert expected["failures"] == projected_failures
        assert expected["qualified"] == (not refusal)
        if strong_native:
            assert set(guarded_outputs) == (
                {"C-native-four", "C-native-earlier"}
                if release == 24
                else {"C-native-four"}
            )
            for arm in ("P", "C"):
                raw = data(arm + "-withheld-ordinary-repeat-old/stdout")
                assert (
                    b"1 failed;" in raw
                    and b"script_tag" in raw
                    and b"source_text" in raw
                )
            if release == 24:
                control = j("before-output-selection.json")
                assert control["phase"] == "C-before-output-control-" + str(
                    max([2] + extra)
                )
                assert len(control["targets"]) == 2 and E2E in control["targets"]
                assert (
                    set(control["targets"])
                    <= phases[control["phase"]]["native"]["fresh"].keys()
                )

        for arm in ("P", "C"):
            raw = data(arm + "-withheld-old-on-new/stdout")
            assert (
                b"1 failed;" in raw and b"script_tag" in raw and b"source_text" in raw
            )
        assert j("C-native-four-verdict.json") == {"exit": 83, "stdout_bytes": 0}
        for mode in ("four", "save"):
            mut = j("C-native-" + mode + "-actual-change.json")
            assert (
                len(mut["changed_offsets"]) == 4
                and mut["symbol_before"] != mut["symbol_after"]
            )
        opath_phase, repair_phase = ("C-distinct-OPATHs", "C-actual-output-repair")
        if plain:
            opath_phase, repair_phase = unmetered_reader.output_controls(
                j, phases, subset, E2E
            )
        corrupt = j(repair_phase + "/physical-decisions.json")["actors"][E2E]
        assert (
            corrupt["action"] == "full"
            and "output-bytes-or-generation" in corrupt["reasons"]
        )
        if release == 24:
            opath = j("actual-canonical-OPATHs.json")
            assert len(opath) == 2 and E2E in opath
            repaired = j(repair_phase + "/physical-decisions.json")["actors"]
            for k, obs in opath.items():
                assert (
                    obs["held_ns"] > 0
                    and obs["old"][4] == 0
                    and obs["old"][:2] != obs["new"]
                )
                assert k in phases[opath_phase]["native"]["fresh"]
                assert (
                    repaired[k]["action"] == "full"
                    and "output-bytes-or-generation" in repaired[k]["reasons"]
                )
        accepted = not refusal
    return {
        "admission": enroll,
        "ordinary_second_edit": ordinary,
        "sha256": expected_sha,
        "archive_bytes": path.stat().st_size,
        "stage_count": len(phases),
        "registered_stages": len(names),
        "guarded_native_outputs": guarded_outputs,
        "complete": "complete.json" in members,
        "qualified": accepted,
        "refusal": refusal,
        "all_native_differences": complement,
        "clocks": timed,
        "native": {k: v["native"] for k, v in phases.items() if "native" in v},
        "actual_execs": {
            k: v["physical_execs"] for k, v in phases.items() if "physical_execs" in v
        },
        "extra_edited_native": {
            k: v["other_native_full"]
            for k, v in phases.items()
            if "other_native_full" in v
        },
        "list_sha256": list_sha,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            intake(
                Path(sys.argv[1]),
                sys.argv[2],
                sys.argv[3],
                int(sys.argv[4]),
                int(sys.argv[5]),
            ),
            indent=2,
            sort_keys=True,
        )
    )
