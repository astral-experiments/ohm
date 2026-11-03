"""Check a full, deliberately unlisted native output after a new -L search selects libutil.a."""
import gzip
import json
from pathlib import Path

import coordinator


def check(actor, raw, mutation, provider, actual, old_sha):
    op = coordinator.rows(raw)
    mode = mutation["mode"]
    assert mode in ("earlier", "four")
    assert actor["key"] != actor["prior"]["key"] and actor["response"] == "full"
    assert actor["action"] == "full-typed-refusal" and actor["allowed"] is False
    assert "from_full_stage" not in actor and "physical" not in actor
    assert op["MISS"] == [["coordinator-full"]] and op["VERIFIED"] == [[]]
    assert not any(op[k] for k in ("ACCEPT", "FRESH-PUBLISH", "FRESH-GENERATIONS", "REFUSED", "WARNING"))
    assert op["ACTUAL-GROUP"] and op["PROJECTED-GROUP"] == op["ACTUAL-GROUP"]
    assert op["DOMAINS"] == [["true", "true", "2"]]
    (admission,) = op["ADMISSION"]
    assert admission[0] == "false" and coordinator.HASH.fullmatch(admission[1])
    (emitted,) = op["EMITTED"]
    assert emitted == [str(n) for n in actual["identity"]] + [actual["blake3"], actual["path"]]

    (shadow,) = [v for v in op["FROZEN"] if v[-1].endswith("/raw-dylibs/libutil.a")]
    dev, ino, n, digest, path = shadow
    assert int(n) == provider["bytes"] > 0 and digest == provider["blake3"]
    assert provider["sha256"] == mutation["provider"]
    (symbol,) = [v for v in op["FROZEN"] if v[-1].endswith("/symbols.o")]
    assert Path(symbol[-1]).parent == Path(path).parent.parent
    for item in (shadow, symbol):
        (used,) = [v for v in op["USED"] if v[-1] == item[-1]]
        assert used[1:3] == item[2:4]
    # Require the actual search result and the same physical open generation as the immutable input.
    quoted = json.dumps(path)
    (selected,) = [v for v in op["OHMLOOK"] if v[0] == "E" and v[-1] == "Some(" + quoted + ")"]
    (opened,) = [v for v in op["OHMLOOK"] if v[0] == "O" and v[3] == quoted]
    assert opened[1:3] == selected[1:3] and selected[1] == actor["pid"]
    assert opened[4:] == [dev, ino, n]
    if mode == "four":
        off = mutation["changed_offsets"]
        assert len(off) == 4 and off == list(range(off[0], off[0] + 4))
        assert mutation["symbol_before"] != mutation["symbol_after"]
        assert old_sha != actual["sha256"] and actor["prior"]["output"] != actual["blake3"]
    else:
        assert "changed_offsets" not in mutation and mutation["symbol_before"] == mutation["symbol_after"]
        assert old_sha == actual["sha256"] and actor["prior"]["output"] == actual["blake3"]
    return {"action": actor["action"], "pid": actor["pid"], "prior_key": actor["prior"]["key"],
            "current_key": actor["key"], "consumed_provider": shadow, "consumed_symbols": symbol,
            "previous_output_sha256": old_sha, "actual_output": actual}


def on_worker(td, role, mutation, provider_path, executable, previous_digest, reported_digest, sha256, blake3):
    actor = json.loads((td / "physical-decisions.json").read_bytes())["actors"][role]
    raw = gzip.decompress((td / ("actor-" + actor["pid"] + ".tsv.gz")).read_bytes()).decode()
    st = executable.lstat()
    assert executable.is_file() and not executable.is_symlink()
    actual = {"path": str(executable), "identity": [st.st_dev, st.st_ino, st.st_size],
              "blake3": blake3(executable), "sha256": sha256(executable)}
    after = executable.lstat()
    assert (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    assert actual["sha256"] == reported_digest
    provider = {"bytes": provider_path.stat().st_size, "blake3": blake3(provider_path), "sha256": sha256(provider_path)}
    return check(actor, raw, mutation, provider, actual, previous_digest)
