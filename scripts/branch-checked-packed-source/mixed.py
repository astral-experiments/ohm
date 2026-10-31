"""Exercise two physical writers without changing either canonical object beside the packed sidecar."""

import subprocess

from objects import digest, dump, escrow, file_sha, need, unpack
from physical import observe


def trial(root, report, env, sdk, driver, activate, identities, consumer):
    report.mkdir()
    work = root / "same-source-mixed-writer"
    work.mkdir()
    cache = work / "incremental"
    program = work / "program"
    src = work / "main.rs"
    env = env | {"CARGO_MANIFEST_DIR": str(work)}

    def transition(branch, value):
        subprocess.run(
            ["git", "symbolic-ref", "HEAD", "refs/heads/" + branch], cwd=work, env=env, check=True
        )
        code = [f"pub fn f{i}(x:u32)->u32{{x.wrapping_add({i})}}" for i in range(384)]
        code += [
            f"static DATA:[u8;32768]=[{value};32768];",
            'fn main(){println!("{}",f0(std::hint::black_box(&DATA)[0].into()));}',
        ]
        src.write_text("\n".join(code) + "\n")

    def sessions():
        return {
            p
            for p in cache.glob("shadow_legacy-*/s-*")
            if p.is_dir() and not p.name.endswith("-working")
        }

    def visit(label, role, want):
        activate(role)
        need(file_sha(sdk / driver) == identities[role]["driver"], "foreign installed driver")
        argv = [
            "rustc",
            "+ohm",
            "main.rs",
            "--crate-name",
            "shadow_legacy",
            "-Ccodegen-units=1",
            "-Cdebuginfo=0",
            "-Cincremental=" + str(cache),
            "-Zohm-branch-cache=yes",
            "-Zohm-check-relink-inputs",
            "-Zohm-shared-stages",
            "-o",
            str(program),
        ]
        before = sessions()
        program.unlink(missing_ok=True)
        sub = observe(argv, work, env, report, label, sdk / driver, identities[role]["source"])
        (report / (label + ".compiler.stderr")).write_bytes(sub.stderr)
        need(sub.returncode == 0, sub.stderr[-2000:])
        result = subprocess.run([program], cwd=work, env=env, capture_output=True, timeout=10)
        need(
            (result.returncode, result.stdout, result.stderr) == (0, f"{want}\n".encode(), b""),
            "incorrect actual branch program",
        )
        (report / (label + ".runtime")).write_bytes(result.stdout)
        (new,) = sessions() - before
        h = escrow(report / "elf", file_sha(program), program.read_bytes())
        files = {
            p.name: [p.stat().st_dev, p.stat().st_ino, p.stat().st_size, file_sha(p)]
            for p in new.iterdir()
            if p.is_file()
        }
        row = {
            "role": role,
            **identities[role],
            "elf": h,
            "expected": want,
            "session": new.name,
            "source_body": file_sha(src),
            "files": files,
        }
        dump(report / (label + ".json"), row)
        return new, row

    subprocess.run(["git", "init", "-q", "-b", "a"], cwd=work, env=env, check=True)
    transition("a", 17)
    _, a = visit("old-A17", "old", 17)
    transition("b", 29)
    previous, b = visit("old-B29", "old", 29)
    candidates = []
    for p in previous.glob("ohm-packed-object-*"):
        name, body = unpack(p.read_bytes(), p.name, previous.name)
        if b"\x1d" * 8192 in body:
            candidates.append((p, name, body))
    ((side, name, body),) = candidates
    need(not (previous / name).exists(), "old writer left a raw alternative")
    key = side.name
    escrow(report / "inputs", "packed-29", side.read_bytes())
    escrow(report / "inputs", "decoded-29", body)
    transition("b", 83)
    current, f = visit("F-B83", "F", 83)
    x = f["files"][key]
    y = b["files"][key]
    need(
        x == y and name in f["files"] and name not in b["files"], "F did not carry the old packed inode"
    )
    raw = (current / name).read_bytes()
    need(
        raw != body and b"\x53" * 8192 in raw and b"\x1d" * 8192 not in raw,
        "F did not produce distinct source-correct raw data",
    )
    escrow(report / "inputs", "raw-83", raw)
    mark = current / "mixed-source-marker"
    mark.write_text("only_F_B83\n")
    new, n = visit("read-B83", consumer, 83)
    marked = (new / mark.name).is_file()
    need(marked == (consumer == "old"), "wrong raw-vs-packed ownership decision")
    cache.rename(work / "sealed-source")
    _, clean = visit("empty-B83", consumer, 83)
    need(
        a["elf"] != b["elf"] != f["elf"]
        and f["elf"] == n["elf"] == clean["elf"]
        and n["source_body"] == f["source_body"] == clean["source_body"]
        and mark.name not in clean["files"],
        "reader disagrees with its own complete clean ELF",
    )
    result = {
        "producer": "old",
        "bridge": "F",
        "consumer": consumer,
        "source_drivers": identities,
        "object": name,
        "packed_name": key,
        "carried": x,
        "decoded_29": digest(body),
        "raw_83": digest(raw),
        "marker": marked,
        "clean": clean["elf"],
        "compiler_created_both": True,
    }
    dump(report / "complete.json", result)
