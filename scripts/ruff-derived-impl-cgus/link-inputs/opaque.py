"""Exercise a real native search-path replacement on one independently relinked test binary."""

import os
import subprocess
from pathlib import Path

from objects import digest, require, sha


def challenge(actor, argv, output_index, cwd, env, pipes, reference):
    # A private -L directory provides a controlled alternative to the installed libgcc_s.
    # No command targets the original output or writes to an existing toolchain/native input.
    private = actor / "native-search-control"
    private.mkdir()
    require(
        "-lgcc_s" in argv and not any(ch.isspace() for ch in str(private)),
        "missing native library",
    )
    gcc = subprocess.check_output(
        ["cc", "-print-file-name=libgcc_s.so.1"], env=env, text=True
    ).strip()
    library = Path(gcc).resolve(strict=True)
    require(
        library.is_file() and library.name == "libgcc_s.so.1",
        "missing physical native DSO",
    )
    receipt = {
        "extra_search": str(private),
        "system_provider": [str(library), digest(library)],
        "cases": {},
    }

    def run(label, expected):
        exe = private / label
        cmd = argv.copy()
        cmd[output_index] = str(exe)
        cmd.insert(1, "-L" + str(private))
        link = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            pass_fds=pipes,
            capture_output=True,
            timeout=150,
            check=False,
        )
        item = {
            "link": link.returncode,
            "stdout": link.stdout.decode(errors="replace"),
            "stderr": link.stderr.decode(errors="replace"),
        }
        receipt["cases"][label] = item
        if expected is None:
            require(
                link.returncode != 0 and link.stderr,
                "malformed earlier native shadow passed",
            )
            return
        require(
            link.returncode == 0 and exe.is_file(),
            "native shadow could not link: " + item["stderr"][-1000:],
        )
        inventory = subprocess.run(
            [exe, "--list", "--format", "terse"],
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        item.update(
            elf=digest(exe),
            size=exe.stat().st_size,
            verdict=inventory.returncode,
            inventory_sha=sha(inventory.stdout),
        )
        require(
            inventory.returncode == expected,
            ("native shadow verdict", label, inventory.returncode, expected),
        )
        if expected == 0:
            require(
                item["elf"] == reference["sha256"]
                and item["size"] == reference["bytes"]
                and b": test" in inventory.stdout,
                "changed executable with empty earlier search directory",
            )
        else:
            require(
                item["elf"] != reference["sha256"] and not inventory.stdout,
                "missing linked native change",
            )
        exe.unlink()

    run("empty-directory", 0)
    asm = b""".text
.p2align 4
.type ohm_link_input_proof,@function
ohm_link_input_proof:
 movl $60,%eax
 movl $83,%edi
 syscall
 ud2
.size ohm_link_input_proof, .-ohm_link_input_proof
.section .init_array,"aw",@init_array
.quad ohm_link_input_proof
.section .note.GNU-stack,"",@progbits
"""
    obj = private / "ctor.o"
    subprocess.run(["as", "--64", "-o", obj], cwd=cwd, env=env, input=asm, check=True)
    script = private / "libgcc_s.so"
    # A fresh ELF produced from the real Ruff test inputs must now execute the added constructor.
    script.write_text("GROUP ( " + str(obj) + " " + str(library) + " )\n")
    receipt["script"] = script.read_text()
    receipt["assembler"] = asm.decode()
    receipt["old_object"] = digest(obj)
    stamp = obj.stat()
    receipt["object_mtime_ns"] = stamp.st_mtime_ns
    run("shadow-83", 83)
    data = obj.read_bytes()
    old = b"\xbf\x53\0\0\0\x0f\x05"
    require(data.count(old) == 1, "ambiguous constructor operand")
    obj.write_bytes(data.replace(old, b"\xbf\x54\0\0\0\x0f\x05"))
    os.utime(obj, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    now = obj.stat()
    require(
        (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns)
        == (stamp.st_dev, stamp.st_ino, stamp.st_size, stamp.st_mtime_ns),
        "shadow replacement changed metadata",
    )
    receipt["new_object"] = digest(obj)
    run("same-size-restored-mtime-84", 84)
    require(
        receipt["cases"]["shadow-83"]["elf"]
        != receipt["cases"]["same-size-restored-mtime-84"]["elf"],
        "two native inputs emitted identical executables",
    )
    script.write_text("GROUP ( /ohm-no-such-registered-input/missing.o )\n")
    run("malformed", None)
    script.unlink()
    obj.unlink()
    run("restored-empty-directory", 0)
    return receipt
