"""Describe the strict observer's exit sidecar without admitting a partial family."""
from collections import Counter
import gzip
import hashlib
import os
import stat

from history import need
from images import ns


def lines(path, digest):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        for line in stream:
            need(line.endswith(b"\n"), ("partial native line", path.name))
            digest.update(line)
            yield line[:-1].split(b"\t")


def command_prefix(ledger, catalog, command, cwd):
    """Authenticate the two root images without certifying the subsequent partial family."""
    headers, root, found = {}, None, []
    proxy = os.path.join(os.path.dirname(catalog["proxy"]["path"]), "cargo")
    for row in lines(ledger, hashlib.sha256()):
        if row[0] == b"R":
            need(root is None and int(row[1]) == 1 and int(row[2]) > 0, "wrong native root lifetime")
            root = tuple(map(int, row[1:]))
        elif row[0] == b"I":
            i, dev, ino, size = map(int, row[1:5])
            mode = int(row[5], 8)
            need(i == len(headers) + 1 and stat.S_ISREG(mode), "invalid root executable image")
            headers[i] = [row[8].decode(), dev, ino, mode & 0o7777, size,
                          ns(row[6].decode()), ns(row[7].decode())]
        elif row[0] == b"E":
            seq, g, pid, former, image = map(int, row[1:6])
            exe, directory, request, args = [bytes.fromhex(x.decode()) for x in row[6:]]
            key = "proxy" if not found else "cargo"
            spelling = proxy if not found else catalog["cargo"]["path"]
            wanted = command if not found else [spelling, *command[2:]]
            need((g, pid) == root and former == pid and seq == len(found) + 1 and
                 headers[image] == catalog[key]["identity"] and os.fsdecode(exe) == os.fsdecode(request) == spelling and
                 os.fsdecode(directory) == cwd and args == b"".join(os.fsencode(x) + b"\0" for x in wanted),
                 ("different root command in actual partial ledger", key))
            found.append({"ordinal": seq, "role": key, "image_sha256": headers[image][0]})
            if len(found) == 2:
                return found
    raise ValueError("insufficient root images to bind this refusal to ordinary Ruff")


def inspect(ledger, sidecar):
    primary, secondary = hashlib.sha256(), hashlib.sha256()
    counts, extra, tasks, active, images = Counter(), Counter(), {}, {}, {}
    end = failed = None

    def task(g, p):
        row = tasks.setdefault(g, {"initial_tid": p, "pids": set()})
        row["pids"].add(p)
        return row

    # Use task generations, including the kernel's former TID on a nonleader exec.
    # A numeric TGID alone cannot identify a process across PID reuse.
    for row in lines(ledger, primary):
        tag = row[0].decode()
        need(end is None, "record after native terminal")
        counts[tag] += 1
        if tag == "R":
            g, p = map(int, row[1:])
            active[p] = g
            task(g, p).update(parent=0, tgid=p, group=g)
        elif tag == "N":
            pg, _, _, g, p = map(int, row[1:])
            active[p] = g
            task(g, p)["parent"] = pg
            task(g, p).setdefault("image", tasks[pg].get("image"))
        elif tag == "B":
            g, p, tgid = map(int, row[1:])
            active[p] = g
            leader = active.get(tgid)
            task(g, p).update(tgid=tgid, group=tasks.get(leader, {}).get("group", leader))
        elif tag == "E":
            seq, g, p, former, img = map(int, row[1:6])
            task(g, former)
            if former != p:
                active.pop(former, None)
            active[p] = g
            task(g, p).update(image=seq, last_exec=seq)
            images[seq] = {"image": img, "exe": os.fsdecode(bytes.fromhex(row[6].decode())), "lifetime": g}
        elif tag in ("X", "T", "D"):
            g, p, value = map(int, row[1:])
            task(g, p)[tag] = value
            if tag != "X":
                active.pop(p, None)
        elif tag in ("OK", "REFUSE"):
            end = [v.decode() for v in row]
    need(end is not None, "missing original OK or REFUSE")
    exits, esrch = [], []
    for row in lines(sidecar, secondary):
        tag, *fields = row
        tag = tag.decode()
        need(failed is None, "sidecar data after final refusal")
        vals = tuple(map(int, fields))
        extra[tag] += 1
        if tag in ("EXIT", "EXIT_GROUP", "ESRCH"):
            need(len(vals) == 4, ("wrong exit sidecar width", tag))
            g, p, arg, code = vals
            state = tasks.get(g, {})
            need(p in state.get("pids", ()), ("sidecar lifetime or PID absent from kernel prefix", tag, g, p))
            if tag == "ESRCH":
                esrch.append((g, p, arg, code))
            else:
                need(arg == state.get("tgid"), ("exit sidecar TGID disagrees with kernel", tag, g, p))
                if tag == "EXIT_GROUP":
                    exits.append((g, p, arg, code))
        elif tag == "REFUSE_FINAL":
            need(len(vals) == 10, "refusal field count")
            failed = dict(zip(("tid", "lifetime", "raw_wait", "tgid", "known", "born", "exit_seen", "pending",
                               "spawned", "last_exec"), vals))
        else:
            raise ValueError(("unknown exit-sidecar record", tag))
    result = {"ledger_sha256": primary.hexdigest(), "sidecar_sha256": secondary.hexdigest(), "terminal": end,
              "core_events": dict(sorted(counts.items())), "sidecar_events": dict(sorted(extra.items()))}
    if end[0] == "OK":
        need(failed is None and bool(exits), "incomplete exit sidecar on native success")
        return result
    need(len(end) == 3 and (end[1] == "unclosed final task") == (failed is not None), "wrong refusal witnesses")
    if failed is None:
        return result
    g, p = failed["lifetime"], failed["tid"]
    state = tasks.get(g, {})
    need(os.WIFEXITED(failed["raw_wait"]) or os.WIFSIGNALED(failed["raw_wait"]), "nonterminal wait")
    need(all(failed[k] in (0, 1) for k in ("known", "born", "exit_seen")) and 0 <= failed["pending"] <= 3,
         "invalid strict task state")
    need(not (failed["known"] and failed["born"] and failed["exit_seen"] and not failed["pending"]),
         "diagnostic would pass the unchanged strict gate")
    need((not state or p in state["pids"]) and bool(failed["known"]) == ("parent" in state) and
         bool(failed["born"]) == ("tgid" in state) and failed["tgid"] == state.get("tgid", 0) and
         bool(failed["exit_seen"]) == ("X" in state) and not ({"T", "D"} & state.keys()) and
         failed["last_exec"] == state.get("last_exec", 0), "refusal fields inconsistent with strict ledger prefix")
    group = state.get("group")
    def summary(s):
        return {key: s[key] for key in ("initial_tid", "parent", "tgid", "group", "X", "T", "D") if key in s}
    issuers = [{"lifetime": i, "tid": tid, "exit_group_arg": code, "kernel": summary(tasks[i]),
                "installed_image": images.get(tasks[i].get("image"))}
               for i, tid, _, code in exits if group is not None and tasks[i].get("group") == group]
    result.update(refused_task=failed, kernel_prefix=summary(state), inherited_or_own_image=images.get(state.get("image")),
                  previous_same_tid=[{"lifetime": i, "kernel": summary(s)} for i, s in tasks.items()
                                     if i != g and p in s["pids"]],
                  same_group_exit_syscalls=issuers,
                  same_group_resume_esrch=[row for row in esrch if row[0] == g or
                                          (group is not None and tasks[row[0]].get("group") == group)])
    return result
