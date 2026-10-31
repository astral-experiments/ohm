"""Verify the native and storage witnesses in one original hosted artifact after the inherited clocks were collected."""

import gzip
import json
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clocked as c
import products
import ingress
import qualification, semantic_readback


def archive_bytes(members, body):
    rebuilt = bytearray(b"!<arch>\n")
    for _, header, digest, length, pad in members["entries"]:
        blob = body(digest)
        c.require(c.sha(blob) == digest and len(blob) == length, digest)
        rebuilt += bytes.fromhex(header) + blob + bytes.fromhex(pad)
    c.require(
        len(rebuilt) == members["bytes"] and c.sha(rebuilt) == members["sha256"], "complete archive replay"
    )
    return bytes(rebuilt)


def verify(path, pinned):
    c.require(c.file_sha(path) == pinned, "original GitHub artifact digest")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        c.require(len(names) == len(z.namelist()) and z.testzip() is None, "ZIP member integrity")

        def locate(end):
            found = [n for n in names if n == end or n.endswith("/" + end)]
            c.require(len(found) == 1, end)
            return found[0]

        def raw(end):
            return z.read(locate(end))

        def doc(end):
            return json.loads(raw(end))

        prefix = "musl-measurements/"
        pair = doc(prefix + "pair.json")
        hand = doc(prefix + "admission.json")
        config, cert = ingress.admitted(HERE, pair["phase"])
        c.require(hand["admitted"] == cert and hand["transfer"] == config["source_transfer"], "authenticated source and both provider histories")
        _,opaque=qualification.previous(HERE,config)
        c.require(doc(prefix+"opaque-consumer-sources.json")==opaque["consumer_sources"],"qualified ten-method source set differs")
        c.require(qualification.source(gzip.decompress(raw(prefix+"nodes.rs.gz")))==opaque["finite_source"]==doc(prefix+"finite-source.json"),"source-pinned lifetime admission")
        c.require(hand["opaque_preflight"]==opaque and pair["original_failed_hardware"]==opaque["excluded_hardware_run"]
                  and pair["boot_id"] not in opaque["excluded_hardware_boots"] and pair["opaque_qualification"]==opaque["passed_artifact_sha256"],"failed screen or wrong semantic qualification")
        for key in ("source_run", "source_head", "provider_run", "provider_head"):
            c.require(pair[key] == hand["transfer"][key.upper()] == str(config[key]), ("source or provider mismatch", key))
        for role in "PC":
            c.require(cert["ordinary_sha256"][role] == hand["qualification"][role]["artifact_sha256"], ("ordinary artifact mismatch", role))
        info = doc(prefix + "packet.json")
        packed = raw(info["file"])
        c.require(c.sha(packed) == info["sha256"] and len(packed) == info["bytes"], "compact clock record")
        envelope = json.loads(
            subprocess.run(["zstd", "-qdc"], input=packed, capture_output=True, check=True).stdout
        )
        for n, v in envelope.items():
            c.require(v.encode() == raw(n), n)
        c.require(
            pair["order"] == c.assignment(HERE, pair["phase"])[pair["position"] - 1]
            and pair["hardware"]
            and pair["whole_command"] == c.CMD
            and pair["boot_id"] == doc(prefix + "host.json")["boot_id"],
            "pair enrollment",
        )
        summary = {}
        for role in pair["order"]:
            arm = prefix + role + "/"
            terminal = doc(arm + "terminal.json")
            c.require(c.sha(raw(arm + "terminal.json")) == pair["terminals"][role], role)
            for endpoint in c.PHASES:
                stream = doc(arm + endpoint + "/streams.json")
                c.check_clock(doc(arm + endpoint + "/clock.json"))
                for kind in ("stdout", "stderr"):
                    content = raw(arm + endpoint + "/" + kind + ".raw")
                    c.require(
                        stream[kind] == {"bytes": len(content), "sha256": c.sha(content)},
                        "physical process streams",
                    )
            for name, st in terminal["artifacts"].items():
                base = arm + "proof/" + name + "/"
                members = doc(base + "ar-replay.json")

                def native_body(digest):
                    b = gzip.decompress(raw(arm + "proof/ar-content/" + digest + ".gz"))
                    c.require(c.sha(b) == digest, "real original native input")
                    return b

                canon = products.normalized_archive(archive_bytes(members, native_body))
                image = subprocess.run(
                    ["zstd", "-qdc"], input=raw("images/" + st["elf"] + ".zst"), capture_output=True, check=True
                ).stdout
                c.require(
                    st["rlib"] == members["sha256"] == canon["raw"]
                    and st["canonical_rlib"] == canon["complete_canonical_sha256"]
                    and len(image) == st["elf_bytes"]
                    and c.sha(image) == st["elf"]
                    and c.sha(native_body(members["separate_rmeta"])) == st["rmeta"],
                    "entire actual rlib, .rmeta and ELF",
                )
            named=semantic_readback.verify(arm,terminal,opaque,raw)
            for state, sub in [("warm", "measured-final"), ("empty", "empty")]:
                ledger = terminal["storage"][state]
                buf = raw(arm + "proof/" + sub + "/allocated-inodes.json.gz")
                rows = json.loads(gzip.decompress(buf))
                c.require(
                    c.sha(buf) == ledger["raw_gzip_sha256"]
                    and c.sha(gzip.decompress(buf)) == ledger["raw_sha256"],
                    "original allocation witness",
                )
                unique = {(r[1], r[2]): r[5] for r in rows}
                c.require(
                    sum(512 * b for b in unique.values()) == ledger["allocated_unique"]
                    and len(rows) - len(unique) == ledger["hardlink_aliases"],
                    "unique GNU allocated blocks and aliases",
                )
            summary[role] = {
                "complete_native_visits": len(terminal["artifacts"]),
                "named_archive_checks": named,
                "storage": {k: v["allocated_unique"] for k, v in terminal["storage"].items()},
            }
        return {
            "phase": pair["phase"],
            "position": pair["position"],
            "order": pair["order"],
            "boot": pair["boot_id"],
            "physical": summary,
        }


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]), sys.argv[2]), indent=2))
