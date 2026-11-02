import gdb
import json
import os

path = os.environ["OHM_GDB_SOURCE"]
result = []
for requested in json.loads(os.environ["OHM_GDB_LINES"]):
    records = []
    try:
        _, locations = gdb.decode_line(f"{path}:{requested}")
    except gdb.error:
        locations = []
    for location in locations or []:
        if not location.pc:
            continue
        actual = gdb.find_pc_line(location.pc)
        if not actual.symtab or not actual.symtab.filename.endswith(path):
            continue
        try:
            block = gdb.block_for_pc(location.pc)
            while block and not block.function:
                block = block.superblock
            function = block.function.print_name if block and block.function else None
        except (RuntimeError, gdb.error):
            function = None
        records.append([actual.line, actual.symtab.filename, function, hex(location.pc)])
    result.append({"requested": requested, "records": sorted(records, key=str)})
print("OHM_SITES " + json.dumps(result, sort_keys=True))
