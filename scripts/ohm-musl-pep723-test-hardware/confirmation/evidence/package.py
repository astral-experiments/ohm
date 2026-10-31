"""Preserve original counter, Cargo, native-result and storage records for offline replay."""

import argparse
import gzip
import hashlib
import io
import json
import shutil
import tarfile
import zipfile
from pathlib import Path


def selected():
    yield from ('POSITION.sha256', 'counts/pair.json', 'counts/confirmation-host.json')
    yield 'counts/calibration/summary.json'
    for n in range(28):
        yield f'counts/calibration/{n}.json'
    for arm in 'PC':
        base = f'counts/{arm}/'
        yield base + 'terminal.json'
        for visit in ('edit', 'repeat'):
            yield base + visit + '/clock.json'
            yield base + visit + '/stdout.raw'
        yield base + 'measured-final/allocated-inodes.json.gz'
        yield f'flanks/{arm}/empty-new/allocated-inodes.json.gz'
        for visit in ('old', 'edit', 'wrong', 'repair', 'empty-new'):
            yield f'flanks/{arm}/{visit}/native-list.stdout.gz'
            yield f'flanks/{arm}/{visit}/native-full.stdout.gz'
        yield f'flanks/{arm}/invalid/stdout.gz'


def main(originals, report, dest):
    official = json.loads((originals / 'official.json').read_bytes())
    result = json.loads(report.read_bytes())
    assert result['head'] == official['head'] and result['run'] == official['run']
    assert result['qualifies'] and official['conclusion'] == 'success' and len(official['positions']) == 12
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(originals / 'official.json', dest / 'originals.json')
    shutil.copyfile(report, dest / 'report.json')
    with (dest / 'counters.tar.gz').open('wb') as f, gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|') as tar:
            for position in official['positions']:
                name = f"{position['block']:02}-{position['position']}"
                src = originals / (name + '.zip')
                with src.open('rb') as original:
                    assert hashlib.file_digest(original, 'sha256').hexdigest() == position['sha256']
                with zipfile.ZipFile(src) as z:
                    for path in selected():
                        data = z.read(path)
                        info = tarfile.TarInfo(name + '/' + path)
                        info.size = len(data)
                        tar.addfile(info, io.BytesIO(data))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('originals', 'report', 'dest'):
        p.add_argument(arg, type=Path)
    a = p.parse_args()
    main(a.originals, a.report, a.dest)
