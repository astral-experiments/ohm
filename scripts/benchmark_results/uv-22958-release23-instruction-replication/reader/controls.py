"""Adverse checks using overlays on one admitted marginal primary, with no extra measurements."""
from copy import deepcopy
import json
import struct
from zipfile import ZipFile
import paired
import release23_verdict
import split_host


class Changed:
    def __init__(self, original, name, value):
        self.archive, self.name, self.value = original, name, value

    def read(self, name):
        if name == self.name:
            return json.dumps(self.value).encode()
        return self.archive.read(name)


def refused(fn):
    try:
        fn()
    except (ValueError, AssertionError):
        return
    raise AssertionError("Expected a rejection")


def run(archive, admitted, actual):
    with ZipFile(archive) as z:
        prefix = "native-22958/1-S/"
        boot = paired.member(z, "boot-attestation.json")
        def check(name, mutate):
            path = prefix + name
            row = paired.member(z, path)
            mutate(row)
            refused(lambda: paired.open_arm(Changed(z, path, row), 1, "S", boot["boot"], boot["affinity"]))
        def one_raw_word(row):
            item = row["targets"]["uv_client"]
            fields = list(struct.unpack("<4Q", bytes.fromhex(item["raw_hex"])))
            fields[0] -= 1
            item["raw_hex"] = struct.pack("<4Q", *fields).hex()
        check("threads/per-rustc.json", one_raw_word)
        check("threads/per-rustc.json", lambda r: r["targets"]["uv_client"].update(pid=r["root"]))
        check("whole/whole-clock.json", lambda v: v.update(running=v["enabled"]-1))
        check("wall/ordinary.json", lambda v: v.update(end_ns=v["end_ns"]+1))
        check("wall/ordinary.json", lambda v: v.update(wait="Popen.wait(timeout=...)"))
        service = paired.member(z, "placement/current-run.json")
        jobs = paired.member(z, "placement/current-jobs.json")
        refused(lambda: split_host.service_assignment(service, jobs, admitted["run"]+1, boot["coordinator"], split_host.BRANCH))
    metrics = {k: {"control_and_treatment": deepcopy(v)} for k, v in actual["raw"].items()}
    values = metrics["sum_two"]["control_and_treatment"]
    values[3][1] += 1
    refused(lambda: release23_verdict.verdict(metrics))
    values[3][1] -= 1
    client = metrics["uv_client"]["control_and_treatment"]
    old = client[3][1]
    client[3][1] = client[3][0] * 4 // 5 + 1
    values[3][1] += client[3][1] - old
    dec = release23_verdict.verdict(metrics)["instruction_declarations"]["uv_client"]
    assert dec["pairs_at_least_20_percent"] == 7 and not dec["qualifies_20_percent"]
    return 8
