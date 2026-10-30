"""Bind the two independent allocations, all source transports, and the actual native release products before observing a clock."""
from pathlib import Path
import gzip
import hashlib
import itertools
import json
import sys
import unittest
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here))
import objc2_clock
import release_cli
from release_bins import freeze,selected,stamp
from release_import import ART,CARGO,SHA
from study import CHILD,PARENT
from versioned_select import AWARE,CLASSIC,CARGOS
import versioned_selftest as previous
class Release(unittest.TestCase):
    test_actual_depfile_rules=previous.Protocol.test_exact_dummy_rules
    test_reject_bad_marker_witness=previous.Protocol.test_opaque_suffix_and_wrong_indices
    def test_source_and_binary_custody(self):
        z=previous.source
        records=z.SOURCES
        self.assertEqual(records['rust-parent']['source'],PARENT)
        self.assertEqual(records['cargo-gnu']['base'],CLASSIC)
        for label,rec in records.items():
            raw=(z.FILES/(label+'.commit')).read_bytes()
            patch=gzip.decompress((z.FILES/(label+'.patch.gz')).read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(),rec['commit_sha256'])
            self.assertEqual(hashlib.sha256(patch).hexdigest(),rec['patch_sha256'])
            self.assertEqual(hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),rec['source'])
            self.assertEqual(raw.splitlines()[:2],[('tree '+rec['tree']).encode(),('parent '+rec['base']).encode()])
        spec=json.loads((here/'release-rust/source.json').read_bytes())
        bulk=(here/'release-rust/source.pack').read_bytes()
        self.assertEqual((spec['child'],spec['objects'],spec['bytes'],spec['sha256']),(CHILD,81,len(bulk),hashlib.sha256(bulk).hexdigest()))
        self.assertEqual(spec['vertices'][CHILD][':compiler'],spec['vertices'][records['rust-objc']['source']][':compiler'])
        self.assertEqual(spec['vertices'][CHILD][':tests'],spec['vertices'][records['rust-objc']['source']][':tests'])
        self.assertEqual(AWARE,CARGO)
        self.assertEqual(SHA,'9f09941432a849b13ee6177c2f4b0f35f5d9c350e518688d64325ce513ec532d')
        self.assertEqual(ART['cargo'][0],13002072187)
    def test_real_fixtures_and_distinct_schedules(self):
        self.assertEqual((release_cli.INDEX,release_cli.ORDER['screen'],release_cli.ORDER['confirmation']),
                         (428,['PC','CP'],'PC CP CP CP PC CP PC PC PC CP CP PC'.split()))
        self.assertEqual((objc2_clock.ALLOCATION,objc2_clock.ORDERS['screen'],objc2_clock.ORDERS['confirmation']),
                         (257,['PC','CP'],'PC CP PC PC CP CP CP PC PC CP PC CP'.split()))
        self.assertEqual(len(list(itertools.combinations(range(12),6))),924)
        for order in (release_cli.ORDER['confirmation'],objc2_clock.ORDERS['confirmation']):
            self.assertEqual(order.count('PC'),6)
        self.assertEqual(set(CARGOS),{'signed','classic','aware'})
        self.assertEqual(release_cli.CMD,['cargo','+ohm','build','-p','ty','--bin','ty','--locked','--offline','-j4','--message-format=json'])
if __name__=='__main__':
    unittest.main(verbosity=2)
