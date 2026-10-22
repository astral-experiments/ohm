"""Require the published release and its verified Mac installation before running workloads."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RELEASE = 'ohm-1.99.0-7'

def verify_release():
    install = json.loads((ROOT/'release-install/verified-install.json').read_text())
    expected = json.loads((ROOT/'release-install/expected.json').read_text())
    frozen = json.loads((ROOT/'frozen-source.json').read_text())
    assert install['passed'] and install['release'] == expected['release'] == RELEASE
    assert install['target'] == 'aarch64-apple-darwin'
    assert expected['published_at'] and expected['tag_commit'] == frozen['release_commit']
    assert expected['release_run']['status'] == 'completed'
    assert expected['release_run']['conclusion'] == 'success'
    assert expected['release_run']['headSha'] == expected['tag_commit']
    digest = hashlib.sha256((ROOT/'release-install/manifest.json').read_bytes()).hexdigest()
    assert digest == expected['manifest_sha256'] == install['manifest_sha256']
    assert set(install['components']) == {'rustc','cargo','clippy-driver','rustfmt'}
    for name,item in install['components'].items():
        binary = Path(subprocess.check_output(['rustup','which','--toolchain',RELEASE,name],text=True).strip())
        assert binary.resolve() == Path(item['path']).resolve()
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == item['sha256'], name
    for item in json.loads((ROOT/'apfs/disk/tools/verified.json').read_text()):
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['verified_sha256'], item['name']
    return install
