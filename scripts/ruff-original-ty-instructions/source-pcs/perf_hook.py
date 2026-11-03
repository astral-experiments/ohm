"""Linux perf-script plugin. Intern names and keep every sampled instruction pointer and call chain."""
import gzip
import json
import os

out = gzip.open(os.environ['OHM_PERF_ROWS'], 'xt', compresslevel=2)
frames = {}

def frame(dso, symbol, address):
    key = (str(dso), str(symbol or ''))
    if key not in frames:
        index = len(frames) + 1
        frames[key] = index
        print(json.dumps(['f', index, *key], separators=(',', ':')), file=out)
    return [frames[key], int(address)]

def process_event(event):
    sample = event['sample']
    def callsite(member):
        symbol = member.get('sym') or {}
        return frame(member.get('dso'), symbol.get('name') if isinstance(symbol,dict) else symbol, member['ip'])
    leaf = frame(event.get('dso'), event.get('symbol'), sample['ip'])
    stack = [callsite(member) for member in event.get('callchain', [])]
    print(json.dumps(['s', event['ev_name'], sample['pid'], sample['tid'], sample['time'], sample['period'], leaf, stack], separators=(',', ':')), file=out)

def trace_end():
    out.close()
