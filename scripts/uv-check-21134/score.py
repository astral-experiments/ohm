"""Reopen the kernel-selected counts and the two separate original Cargo measurements before reporting a ratio."""

from pathlib import Path
import io, json, os, statistics, sys, zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
from placement import PRIMARY, valid_uuid


def quant(col):
    return {
        "control_median": statistics.median(x for x, y in col),
        "G_median": statistics.median(y for x, y in col),
        "G_over_control": statistics.median(y / x for x, y in col),
        "paired": [y / x for x, y in col],
        "control_and_G": col,
    }


def words(raw):
    return DR["read_counter"](bytes.fromhex(raw))


class Files:
    def __init__(self, path):
        self.z = zipfile.ZipFile(path) if path.is_file() else None
        self.d = path
        if self.z:
            n = self.z.namelist()
            require(
                len(n) == len(set(n)) and all(not k.startswith("/") and ".." not in Path(k).parts for k in n),
                "duplicate or unsafe artifact member",
            )

    def raw(self, name):
        return self.z.read(name) if self.z else (self.d / name).read_bytes()

    def get(self, name):
        return json.loads(self.raw(name))

    def sha(self, name):
        return hashlib.sha256(self.raw(name)).hexdigest()


def validate_scoped(tree, result, forms, compiler_id):
    require(
        tree["root"] == result["root"]
        and tree["exits"][tree["root"]] == 0
        and result["scope"] == "retired userspace instructions in the selected process and its threads",
        "wrong Cargo process or PMU scope",
    )
    observed, allr = forms_from_tree(tree, compiler_id)
    require(observed == forms and set(result["targets"]) == set(forms), "actual complete native selectors")
    bound = {}
    pids = set()
    events = set()
    for name, argv in forms.items():
        v = result["targets"][name]
        matches = [row for row in allr if row["argv"] == argv]
        require(len(matches) == 1, "ambiguous kernel image")
        x = matches[0]
        require(
            v["argv"] == argv
            and v["pid"] == x["pid"]
            and v["file"] == compiler_id
            and v["exe"] == x["exe"] == str(RUSTC),
            "physical PID/argv",
        )
        w = words(v["raw_hex"])
        require(
            all(v[k] == z for k, z in w.items()) and v["pid"] not in pids and v["event_id"] not in events,
            "unknown or reused counter",
        )
        pids.add(v["pid"])
        events.add(v["event_id"])
        bound[name] = w["instructions"]
    return bound


def replay(src):
    f = Files(src)
    boot = f.get("boot-attestation.json")
    idx = f.get("panel/complete.json")
    mode, control = idx["mode"], idx["control"]
    role = "marginal" if control == "F" else "signed"
    require(
        boot["series"] == role + "." + mode
        and boot["series"] in PRIMARY
        and valid_uuid(boot["boot"])
        and boot["boot"] not in boot["excluded"],
        "wrong series or host",
    )
    require(control == "F" and role == "marginal", "the signed R arm failed native admission on this edit")
    require(
        boot["protocol"] == sha(HERE / "protocol.json") and idx["orders"] == P["orders"][mode],
        "wrong numerical registration",
    )
    require(
        boot["inherited"] == f.sha("calibration.json")
        and boot["threads"] == f.sha("per-rustc-calibration/calibration.json")
        and boot["blocking"] == f.sha("blocking-clock-pre/verified.json"),
        "calibration readback",
    )
    release = P["roles"]["R"]["release"]
    for name in ("latest-before.json", "latest-after.json"):
        x = f.get(name)
        require(
            x["id"] == release and x["immutable"] and not x["draft"] and not x["prerelease"],
            "changed release",
        )
    require(set(idx["native"]) == {control, "G"}, "native opening")
    ref = {}
    for label in (control, "G"):
        where = "panel/opening-" + label + "/"
        o = f.get(where + "native-accepted.json")
        require(
            o["score"] is None
            and o["role"] == label
            and idx["native"][label] == f.sha(where + "native-accepted.json")
            and o["behavior"]
            and len(o["owners"]) == 3,
            "opening/native outcome",
        )
        ref[label] = f.get(where + "first-B/observed.json")["forms"]
    from cold import validate as cold_validate

    cross = f.get("panel/cross-role-native.json")
    for label in (control, "G"):
        prefix = "panel/opening-" + label + "/"
        require(
            cross["first-B"][label] == f.sha(prefix + "first-B/products.json")
            and all(
                product_roster(f.get(prefix + k + "/products.json")) == cross["logical_products"]
                for k in ("cold-A", "ordinary-first-B", "first-B", "fresh-B")
            ),
            "independent product roster",
        )
    require(cross["native_behavior"][control] == cross["native_behavior"]["G"], "independent native behavior")
    pairs = []
    seed_runs = set()
    for i, order in enumerate(P["orders"][mode], 1):
        counts = {}
        for tag in order.split("/"):
            label = control if tag == "control" else tag
            d = "panel/" + str(i) + "-" + label + "/"
            fi = f.get(d + "first-B/observed.json")
            a = f.get(d + "native-accepted.json")
            require(
                a["role"] == label
                and a["warm"] == f.sha(d + "first-B/products.json")
                and a["cold"] == f.sha(d + "independent-cold-B/products.json")
                and a["complete_separate_visits"],
                "native warm/fresh gate",
            )
            require(
                fi["forms"] == ref[label] and set(fi["forms"]) == set(S["observed_F_dirty_libs"]),
                "actual first-edit scopes",
            )
            req = f.get(d + "request.json")
            require(
                req
                == {
                    "command": CHECK,
                    "environment": ENV,
                    "cwd": str(SRC),
                    "compiler_path": str(RUSTC),
                    "selectors": fi["forms"],
                },
                "different measured process inputs",
            )
            for op in ("unchanged-A", "unchanged-B"):
                v = f.get(d + op + "/observed.json")
                ev = EV["decode"](f.get(d + op + "/kernel-events.json"))
                require(
                    forms_from_tree(ev, v["rustc_id"])[0] == v["forms"] == {}, "real no-op reran a compiler"
                )
            seed = f.get(d + "seed.json")
            cold = f.get(d + "new-cold-A/cold-processes.json")
            cev = d + "new-cold-A/kernel-events.json"
            check = cold_validate(EV["decode"](f.get(cev)), cold["compiler_id"])
            require(
                all(cold[k] == v for k, v in check.items())
                and cold["events"] == f.sha(cev)
                and cold["target_absent"] is True
                and cold["command"] == CHECK
                and cold["end_ns"] > cold["start_ns"] > 0,
                "invalid full fresh-A input",
            )
            identity = cold["start_ns"], cold["root_pid"]
            require(
                identity not in seed_runs
                and seed["role"] == label
                and seed["original_A"] == f.sha(d + "new-cold-A/products.json")
                and seed["bytes_sha256"][0] > 1 << 20,
                "reused cold history",
            )
            seed_runs.add(identity)
            bare = f.get(d + "bare/clock.json")
            require(
                bare["argv"] == CHECK
                and bare["exit"] == 0
                and bare["wait"] == "os.waitpid(child.pid, 0)"
                and bare["end_ns"] - bare["start_ns"] == bare["ns"] > 0
                and b"Finished" in f.raw(d + "bare/stderr"),
                "ordinary Cargo wait",
            )
            whole = f.get(d + "whole/raw.json")
            require(
                whole["code"] == 0
                and whole["event_errno"] == 0
                and whole["enabled"] == whole["running"] > 0
                and whole["instructions"] > 0
                and b"Finished" in f.raw(d + "whole/stderr"),
                "whole-Cargo PMU",
            )
            provider = validate_scoped(
                EV["decode"](f.get(d + "per-rustc/kernel-events.json")),
                f.get(d + "per-rustc/per-rustc.json"),
                req["selectors"],
                f.get(d + "per-rustc/images.json")["rustc"],
            )
            normal = f.get(d + "first-B/products.json")
            require(
                all(f.get(d + x + "/products.json") == normal for x in ("bare", "whole", "per-rustc")),
                "changed scoped/whole/bare output",
            )
            counts[label] = provider | {
                "sum_all_actual_rustcs": sum(provider.values()),
                "whole_cargo_instructions": whole["instructions"],
                "bare_cargo_ns": bare["ns"],
            }
        pairs.append(counts)
    metrics = {k: quant([(v[control][k], v["G"][k]) for v in pairs]) for k in pairs[0]["G"]}

    def passed(metric, bound):
        ratios = metrics[metric]["paired"]
        return {
            "all_eight": all(x < bound for x in ratios),
            "first_four": all(x < bound for x in ratios[:4]),
            "second_four": all(x < bound for x in ratios[4:]),
            "strict_bound": bound,
        }

    res = {
        "source": {"control": P["roles"][control]["rust"], "G": P["roles"]["G"]["rust"]},
        "series": boot["series"],
        "boot": boot["boot"],
        "run": boot["run"],
        "job": boot["job"],
        "head": boot["head"],
        "known_excluded": boot["excluded"],
        "protocol": boot["protocol"],
        "G_lock": boot["G_lock"],
        "control": control,
        "metrics": metrics,
        "thresholds": {
            "uv_20pct_reduction": passed("uv", 0.80),
            "whole_wall_twice_as_fast": passed("bare_cargo_ns", 0.5),
        },
        "physical_pid_records": sum(len(c[arm]) - 3 for c in pairs for arm in (control, "G")),
    }
    require(res["physical_pid_records"] == 8 * 2 * len(S["observed_F_dirty_libs"]), "incomplete PID panel")
    return res


def jointly(first, second):
    a, b = first, second
    require(
        a["control"] == b["control"]
        and a["series"].split(".")[-1] == "initial"
        and b["series"].split(".")[-1] == "repeat"
        and a["boot"] != b["boot"]
        and a["boot"] in b["known_excluded"]
        and a["run"] != b["run"]
        and a["head"] == b["head"]
        and a["protocol"] == b["protocol"]
        and a["G_lock"] == b["G_lock"]
        and a["source"] == b["source"],
        "mixed source or nonindependent host",
    )
    return {k: all(x["thresholds"][k]["all_eight"] for x in (a, b)) for k in a["thresholds"]}


if __name__ == "__main__":
    results = [replay(Path(p)) for p in sys.argv[1:]]
    require(len(results) in (1, 2), "one intact run or independent matching pair")
    print(
        json.dumps(
            {"runs": results, "replicated": jointly(*results) if len(results) == 2 else None},
            indent=1,
            sort_keys=True,
        )
    )
