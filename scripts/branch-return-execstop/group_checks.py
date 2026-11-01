"""Reopen kernel group-exit controls from their original bytes."""
import collections
import gzip
import hashlib
import importlib.util
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
OUTPUT = "8999e7633aff70a36e79bbc057c5102b9c36b0f2ba699fd59bc3f8714a9b4bec"
HISTORY = {
    "01": (13074429247, "comment", "93ac875b4d043e8aa0f9f9c4ec87aa04a07d1bdae757fa742647bbf22b5130bc",
           "69c9473cbf41a41d24b13776b009bdf90b7c895cb84bd7caf88f9a77f5cf6230", "unclosed final task", "2"),
    "02": (13073609945, "X-B", "11c58606667d62c45d1eb6e6399f8c8fdbcdb326b292bd5dd964de9e49d75106",
           "ee1ab1b4b8d74d52eddca09a4e6632d3edb0a8c5add7078374fb2ee8594f3739", "unsupported syscall ABI", "3"),
}

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

reader = load("group_schema_2", HERE / "kernel/read_events.py")
legacy = load("historical_schema_1", HERE / "group-v2/history/v1_reader.py")
wild_fork = load("wild_lifetimes", HERE / "wild_fork.py")
need = reader.need

def records(raw):
    return [line.decode("ascii").split("\t") for line in raw.splitlines()]

def refused(module, raw, **selection):
    try:
        module.parse(raw, **selection)
    except module.Refused as exc:
        return str(exc)
    raise ValueError("admitted a deliberately incomplete or corrupted ledger")

def prior(directory):
    answers = {}
    for pos, (artifact, phase, whole, raw_sha, message, error) in HISTORY.items():
        data = gzip.decompress((directory / (pos + ".tsv.gz")).read_bytes())
        need(hashlib.sha256(data).hexdigest() == raw_sha, "wrong original refusal")
        rows = records(data)
        counts = collections.Counter(row[0] for row in rows)
        need(rows[-1] == ["REFUSE", message, error] and counts["N"] == counts["B"] == counts["C"] == 2101
             and counts["E"] == counts["P"] == 28 and counts["OK"] == 0, "original terminal/projection")
        answers[pos] = dict(run=41283234972, artifact=artifact, phase=phase, zip_sha256=whole, raw_sha256=raw_sha,
                            reason=message, v1=refused(legacy, data), v2=refused(reader, data, expected_schema=2))
    return answers

def mutations(raw):
    rows = records(raw)
    owner = next(row for row in rows if row[0] == "G")
    peer = next(row for row in rows if row[0] == "Q" and row[3] == owner[1])
    reasons = {}
    def trial(name, changed):
        forged = ("\n".join("\t".join(row) for row in changed) + "\n").encode()
        reasons[name] = refused(reader, forged, expected_code=0, expected_schema=3)
    def drop(name, match):
        i = next(i for i, row in enumerate(rows) if match(row))
        trial(name, rows[:i] + rows[i+1:])
    def replace(name, row, where, value):
        trial(name, [r[:where] + [value] + r[where+1:] if r is row else r for r in rows])
    for tag in ("G", "V", "Q", "N", "C", "B", "E", "P", "T", "X"):
        drop("drop-" + tag, lambda r: r[0] == tag and (tag not in ("T", "X") or r[1] == peer[1]))
    for pos, value, name in [(1, owner[1], "park-leader"), (2, owner[2], "peer-tid"),
                             (3, "1", "wrong-owner"), (4, "1", "wrong-tgid")]:
        replace(name, peer, pos, value)
    for nr in ("56", "57", "58", "59", "231", "322", "435", "1073741824"):
        trial("unsafe-park-entry-" + nr, [r[:5] + ["e", nr] if r is peer else r for r in rows])
    i = rows.index(peer)
    trial("live-return-after-park", rows[:i+1] + [["F", peer[1], peer[2], "-2"]] + rows[i+1:])
    replace("wrong-group-status", owner, 3, "36")
    for name, tag in (("missing-owner-exit", "X"), ("missing-owner-wait", "T")):
        drop(name, lambda r: r[0] == tag and r[1] == owner[1])
    trial("whole-group-records-dropped", [r for r in rows if r[0] not in ("G", "Q", "V")])
    trial("old-format-footer", rows[:-1] + [rows[-1][:7]])
    replace("owner-count", rows[-1], 7, "99")
    replace("peer-count", rows[-1], 8, "99")
    need(len(reasons) == 30, "lost a registered mutation")
    return reasons

def physical(event, identity, argv):
    observed = event["image"]
    need(event["argv"] == argv and event["exe"] == identity["resolved"]
         and all(observed[key] == identity[key] for key in ("dev", "ino", "sha256", "mode", "size", "mtime", "ctime")),
         "installed image, physical file or argv changed")

def wild_workers(raw, parsed, rows, counts, argv):
    event, = parsed["execs"]
    need(counts["N"] == 3 and counts["X"] == counts["T"] == 4 and
         counts["G"] == counts["V"] == 1 and counts["H"] == 0 and counts["Q"] in (1, 2),
         "stock Wild must fork once and park at least one of its two threads")
    projected = dict(event=event["ordinal"], lifetime=event["lifetime"], pid=event["pid"],
                     argv=argv, output=argv[argv.index("-o")+1], rustc_event=None, rustc_crate=None)
    evidence, = wild_fork.finish(raw, parsed, [projected])
    leader = next(r for r in rows if r[0] == "G")
    helper = str(evidence["helper"])
    need(evidence["closure"] == "parked" and leader[1:] == [helper, str(evidence["helper_pid"]), "0"]
         and len(evidence["workers"]) == 2 and len(evidence["parked"]) == counts["Q"],
         "wrong inherited helper, workers or group exit")
    # The exit stop (X) may precede another thread's group exit while wait (T) arrives later.
    group_index = rows.index(leader)
    before = []
    for worker in evidence["workers"]:
        life = str(worker)
        birth, = (r for r in rows if r[0] == "N" and r[4] == life)
        need(birth[1:4] == [helper, leader[2], "3"], "worker was not cloned by the enrolled helper")
        stop = rows.index(["X", life, birth[5], "0"])
        if worker in evidence["parked"]:
            park, = (r for r in rows if r[0] == "Q" and r[1] == life)
            need(park[2:5] == [birth[5], helper, leader[2]] and group_index < rows.index(park) < stop,
                 "worker park does not match its group or terminal stop")
        else:
            need(stop < group_index, "unparked worker did not exit before the helper group stop")
            before.append(worker)
    return dict(helper=evidence["helper"], workers=evidence["workers"], parked=evidence["parked"],
                exited_before_group=before)

def positive(raw, stdout, program, argv, identities):
    parsed = reader.parse(raw, expected_code=0, expected_schema=3)
    rows = records(raw)
    counts = collections.Counter(row[0] for row in rows)
    need(parsed["lifetimes"] == parsed["reaped"] == counts["X"] == counts["T"] and
         counts["G"] + counts["H"] == counts["V"] and counts["E"] == counts["P"], "incomplete native exits or images")
    execs = parsed["execs"]
    physical(execs[0], identities[program], argv)
    extra = {}
    if program == "wild":
        need(len(execs) == 1 and not stdout, "unexpected stock Wild image or output")
        extra["worker_schedule"] = wild_workers(raw, parsed, rows, counts, argv)
    else:
        cycles = int(argv[1])
        need(len(execs) == cycles + 1 and counts["T"] == cycles*10 + 1, "missing family member")
        workers = {}; leaders = {}
        for line in stdout.splitlines():
            w = re.fullmatch(rb"worker (\d+) group (\d+)", line)
            if w:
                pid, group = map(int, w.groups())
                need(pid not in workers, "fixture enumerated the same worker twice")
                workers[pid] = group
            else:
                m = re.fullmatch(rb"exiting (\d+) after exec (\d+)", line)
                need(m is not None, "unrecognized independent process inventory")
                group, pid = map(int, m.groups())
                need(group not in leaders, "fixture enumerated the same leader twice")
                leaders[group] = pid
        births = {int(r[2]): int(r[3]) for r in rows if r[0] == "B"}
        waits = {int(r[2]): int(r[3]) for r in rows if r[0] == "T"}
        parents = {int(r[5]): (int(r[2]), int(r[3])) for r in rows if r[0] == "N"}
        need(len(leaders) == cycles and collections.Counter(workers.values()) == {p:8 for p in leaders}
             and set(leaders.values()) == {e["pid"] for e in execs[1:]}, "fixture inventory differs from kernel")
        for group, pid in leaders.items():
            need(parents[group] == (execs[0]["pid"], 1) and parents[pid] == (group, 1)
                 and waits[group] == 37 << 8 and waits[pid] == 0, "wrong real fork group or child")
        for pid, group in workers.items():
            need(births[pid] == group and parents[pid] == (group, 3) and waits[pid] == 37 << 8,
                 "worker was not born and reaped in its declared group")
        for e in execs[1:]:
            physical(e, identities["true"], ["exactly-once"])
    return dict(raw_sha256=parsed["sha256"], counts=dict(counts), lifetimes=parsed["lifetimes"],
                schema=parsed["schema"], images=len(execs), **extra)

def installed(raw, stdout, argv, identity):
    """Match the parked TIDs and exact executed image to the fixture's independent inventory."""
    parsed = reader.parse(raw, expected_code=37, expected_schema=3)
    image, = parsed["execs"]
    physical(image, identity, argv)
    rows = records(raw)
    group, = (row for row in rows if row[0] == "H")
    need(group[1:] == [str(image["lifetime"]),str(image["pid"]),"37",str(image["ordinal"])],
         "wrong installed group leader, status or image")
    workers = set()
    for line in stdout.splitlines():
        match = re.fullmatch(rb"worker (\d+) group (\d+)", line)
        need(match is not None and int(match[2]) == image["pid"], "wrong independent group")
        workers.add(int(match[1]))
    parked = {int(r[2]) for r in rows if r[0] == "Q" and r[3:5] == group[1:3]}
    need(len(workers) == 8 and workers == parked and parsed["lifetimes"] == parsed["reaped"] == 9,
         "an installed worker was omitted")
    def replace(tag, transform):
        return ("\n".join("\t".join(transform(row) if row[0]==tag else row) for row in rows)+"\n").encode()
    corrupt = {
        "missing-installation":replace("H",lambda r:[*r[:4],"0"]),
        "different-installation":replace("H",lambda r:[*r[:4],str(image["ordinal"]+1)]),
        "inherited-image":replace("H",lambda r:["G",*r[1:4]]),
        "wrong-count":replace("OK",lambda r:[*r[:-1],"0"]),
        "old-footer":replace("OK",lambda r:r[:-1]),
    }
    refusals = {k:refused(reader,body,expected_schema=3) for k,body in corrupt.items()}
    refusals["old-reader-selection"] = refused(reader,raw,expected_schema=2)
    return dict(ledger=parsed["sha256"], image_sha256=image["image"]["sha256"],
                ordinal=image["ordinal"], workers=sorted(workers), rejected=refusals)

def pending(raw, stdout, stderr, argv, identity):
    rows = records(raw)
    m = re.fullmatch(rb"pending exec tid=(\d+) group=(\d+)\n", stdout)
    need(m is not None and rows[-1][:2] == ["REFUSE", "fork-group peer has unresolved syscall"]
         and b"fork-group peer has unresolved syscall" in stderr and not any(r[0] in ("OK", "V") for r in rows),
         "did not refuse the seccomp-notified pending exec before releasing its group")
    peer, group = (s.decode() for s in m.groups())
    root, = (r for r in rows if r[0] == "R")
    image, = (r for r in rows if r[0] == "I")
    event, = (r for r in rows if r[0] == "E")
    owner, = (r for r in rows if r[0] == "G")
    worker, = (r for r in rows if r[0] == "B" and r[2:] == [peer, group])
    need(image[1:] == ["1", str(identity["dev"]), str(identity["ino"]), str(identity["size"]),
                        format(identity["mode"], "o"), identity["mtime"], identity["ctime"], identity["sha256"]]
         and event[1:6] == ["1", "1", root[2], root[2], "1"]
         and bytes.fromhex(event[6]) == os.fsencode(identity["resolved"])
         and bytes.fromhex(event[8]) == os.fsencode(argv[0])
         and bytes.fromhex(event[9]) == b"\0".join(map(os.fsencode,argv)) + b"\0",
         "pending fixture executable or argv differs")
    need(owner[2:] == [group, "37"] and ["N", "1", root[2], "1", owner[1], group] in rows
         and ["N", owner[1], group, "3", worker[1], peer] in rows
         and rows[-2][0:2] == ["CONTEXT", group] and rows[-2][3:] == [owner[1], group, "1", "1", "0", "0"],
         "fixture and kernel disagree about pending peer or group")
    return dict(raw_sha256=hashlib.sha256(raw).hexdigest(), refused=refused(reader, raw, expected_schema=2))
