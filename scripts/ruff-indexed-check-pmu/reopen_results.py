"""Recompute the measurements from raw counters, Cargo artifacts, and client diagnostics."""

import gzip, json, re, statistics, sys
from pathlib import Path
from math import comb


def check_records(root, reg, expected_qa):
    def get(p):
        return json.loads(p.read_bytes())

    acc = get(root / "accepted.json")
    assert acc["qa"] == expected_qa and acc["compiler"] == [
        reg["compiler_parent"],
        reg["compiler_candidate"],
    ]
    domain = acc["domain"]
    assert (
        domain in {"native", "Valgrind-guest"}
        and get(root / "domain.json")["domain"] == domain
    )
    calibration = get(root / "calibration" / (domain + ".json"))
    assert calibration["qualified"] and {x["mode"] for x in calibration["cases"]} == {
        "0",
        "1",
        "thread",
        "exec",
    }
    for r in calibration["cases"]:
        samples = []
        for i in range(4):
            d = root / "calibration"
            prefix = domain + "-" + r["mode"] + "-" + str(i)
            samples.append(count(d, prefix, domain))
        assert samples == r["raw"] and len(samples) == 4
        observed = (samples[1] + samples[2] - samples[0] - samples[3]) / 2
        assert (
            r["expected"] == 2 * r["copies"] * 700000
            and abs(observed / r["expected"] - 1) < 0.02
        )
    summary = {}
    for case in reg["source"]:
        d = root / case["name"]
        pairs = []
        counts = {"P": [], "C": []}
        expected = sorted(case["crates"])
        for n in range(reg["pairs"]):
            pair = {}
            for role in ("P", "C"):
                f = d / (str(n) + "-" + role)
                row = get(f / "row.json")
                val = count(f, "B-edit-clock", domain)
                assert (
                    row["count"] == val
                    and val > 100000000
                    and (row["pair"], row["role"], row["domain"]) == (n, role, domain)
                )
                for name, need in [
                    ("A-restored", []),
                    ("B-edit", expected),
                    ("B-repeat", []),
                ]:
                    messages = list(
                        map(
                            json.loads,
                            gzip.decompress(
                                (f / (name + ".stdout.gz")).read_bytes()
                            ).splitlines(),
                        )
                    )
                    assert messages[-1] == {"reason": "build-finished", "success": True}
                    assert (
                        sorted(
                            x["target"]["name"]
                            for x in messages
                            if x["reason"] == "compiler-artifact" and not x["fresh"]
                        )
                        == need
                    )
                clean = get(d / ("clean-B-" + role) / "clean.json")
                assert row["typed"] == clean["verdicts"] and set(row["graphs"]) == set(
                    case["crates"]
                )
                for name, (ec, codes) in row["typed"].items():
                    msgs = list(
                        map(
                            json.loads,
                            gzip.decompress(
                                (f / ("B-" + name + ".stderr.gz")).read_bytes()
                            ).splitlines(),
                        )
                    )
                    assert [
                        m["code"]["code"] for m in msgs if m.get("code")
                    ] == codes and bool(ec) == bool(codes)
                pair[role] = val
                counts[role].append(val)
            pairs.append(1 - pair["C"] / pair["P"])
        data = get(d / "result.json")
        assert data["paired"] == pairs and data[
            "median_reduction"
        ] == statistics.median(pairs)
        positive = sum(v > 0 for v in pairs)
        n = len(pairs)
        assert data["sign_p"] == min(
            1,
            2 * sum(comb(n, i) for i in range(min(positive, n - positive) + 1)) / 2**n,
        )
        assert acc["results"][case["name"]] == {
            k: v for k, v in data.items() if k != "rows"
        }
        summary[case["name"]] = dict(
            pairs=n,
            medians={k: statistics.median(v) for k, v in counts.items()},
            reduction=data["median_reduction"],
            interval=data["bootstrap95"],
            sign_p=data["sign_p"],
        )
    return dict(domain=domain, qa=expected_qa, summary=summary)


def count(directory, prefix, domain):
    if domain == "native":
        v = json.loads((directory / (prefix + ".json")).read_bytes())
        assert (
            v["event_errno"] == v["code"] == 0
            and v["enabled"] == v["running"] > 0
            and v["instructions"] > 0
        )
        return v["instructions"]
    data = gzip.decompress((directory / (prefix + ".lackey.gz")).read_bytes())
    values = re.findall(rb"^==[0-9]+==\s+guest instrs:\s*([0-9,]+)\s*$", data, re.M)
    assert values
    return sum(int(s.replace(b",", b"")) for s in values)


if __name__ == "__main__":
    report = check_records(
        Path(sys.argv[1]),
        json.loads(Path(__file__).with_name("registration.json").read_bytes()),
        sys.argv[2],
    )
    print(json.dumps(report, sort_keys=True, indent=2))
