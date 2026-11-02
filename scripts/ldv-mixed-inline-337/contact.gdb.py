"""Count guarded and fallback calls and bind each one to its actual LLVM Function pointer."""
from pathlib import Path
import json
import gdb

gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set debuginfod enabled off")
gdb.execute("set disable-randomization off")
gdb.execute("handle SIGUSR2 stop print nopass")
gdb.execute("run")
data = json.loads(Path("contact-input.json").read_bytes())
inferior = gdb.selected_inferior()
assert inferior.pid == data["pid"]
trace = []


class Probe(gdb.Breakpoint):
    def __init__(self, kind, address):
        self.kind = kind
        super().__init__("*" + hex(address))
        self.silent = True

    def stop(self):
        pc = int(gdb.parse_and_eval("$pc"))
        assert pc == data["probes"][self.kind]
        # The new-PM fallback returns PreservedAnalyses through a hidden first argument.
        register = "$rsi" if self.kind == "guard" else "$rdx"
        mf = int(gdb.parse_and_eval(register))
        prefix = bytes(inferior.read_memory(mf, 256))
        matches = [(k, offset) for k, addr in data["functions"].items()
                   for offset in range(0, len(prefix), 8)
                   if int.from_bytes(prefix[offset:offset + 8], "little") == addr]
        assert len(matches) == 1, (self.kind, matches)
        name, offset = matches[0]
        trace.append({"function": name, "pass": self.kind, "function_pointer_offset": offset})
        return False


bp = [Probe(kind, address) for kind, address in data["probes"].items()]
gdb.execute("continue")
assert int(gdb.parse_and_eval("$_exitcode")) == 0
assert len({r["function_pointer_offset"] for r in trace}) == 1
expectation = {"line_inline": ["guard", "fallback"], "full_branch": ["guard", "fallback"], "pure_line": ["guard"]}
assert {fn: [r["pass"] for r in trace if r["function"] == fn] for fn in expectation} == expectation, trace
Path("contact-verdict.json").write_text(json.dumps(trace, indent=2) + "\n")
print(trace)
