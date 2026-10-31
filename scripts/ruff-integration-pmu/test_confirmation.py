import copy
import io
import json
from pathlib import Path
import sys
import unittest
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import confirmation as c
import read_original as custody

HEAD="2"*40
RUN=90001

def sample():
    out={}
    for pos in c.POSITIONS:
        boot="12345678-f000-4444-b000-0000000000"+pos
        observations={}
        for arm in c.ARMS:
            observations[arm]={}
            for phase in c.PHASES:
                count=300 if phase.startswith("return-") and arm=="Foff" else 100
                clock={"instructions":count,"code":101 if phase=="invalid" else 0,"event_errno":0,
                       "running":995,"enabled":1000,"user_us":1,"system_us":2,"start":1,"stop":3}
                observations[arm][phase]={"raw_clock":clock,"instructions":count,"exit":clock["code"],"passed":96,
                                         "elf":{"cli":"a","harness":"b","reader":"c"},"allocated":9,"typed":390,"dirty":21}
        out[pos]={"position":pos,"order":c.order(pos),"head":HEAD,"run":RUN,"boot":boot,"observations":observations,
                  "structural":c.admission.SHA,"screen":c.sha((HERE/"qualified-screen.json").read_bytes()),
                  "registration":c.sha((HERE/"PLAN.md").read_bytes()),"unique_clean_elfs":["a","b","c"],"host_filesystem":"test",
                  "calibration":{"cpu":"cpu","pmu":"pmu","abi":"abi","observer":"observer","calibrator":"calibrator","cells":28,"boot":boot}}
    return out

def change(row,arm,phase,x):
    v=row["observations"][arm][phase];v["instructions"]=v["raw_clock"]["instructions"]=x

class ConfirmationTests(unittest.TestCase):
    def test_coverage_and_full_phase_integer_table(self):
        r=c.summarize(sample(),RUN,HEAD)
        self.assertEqual(r["ranks"],[2,11]);self.assertEqual(r["individual_coverage"],"2035/2048")
        self.assertEqual(r["family_coverage_at_least"],"2009/2048")
        self.assertTrue(r["all_three_lower_bounds_strictly_above_two"])
        self.assertEqual(len(r["positions"]),12)
        self.assertEqual(r["positions"]["12"]["raw_instruction_pairs"]["return_sum"],[600,200])
        self.assertEqual(r["positions"]["12"]["raw_instruction_pairs"]["all_seven"],[1100,700])
    def test_exact_lower_rank_and_tie(self):
        rows=sample()
        for pos in ("01","02"):change(rows[pos],"Foff","return-A",200)
        self.assertFalse(c.summarize(rows,RUN,HEAD)["all_three_lower_bounds_strictly_above_two"])
        change(rows["02"],"Foff","return-A",201)
        self.assertTrue(c.summarize(rows,RUN,HEAD)["all_three_lower_bounds_strictly_above_two"])
    def test_sum_can_fail_when_both_individual_intervals_pass(self):
        rows=sample()
        for pos,phase in (("01","return-A"),("02","return-B")):
            change(rows[pos],"Fon",phase,1000);change(rows[pos],"Foff",phase,1000)
        r=c.summarize(rows,RUN,HEAD)
        self.assertEqual(r["distributions"]["return-A"]["rank2"],[3,1])
        self.assertEqual(r["distributions"]["return-B"]["rank2"],[3,1])
        self.assertFalse(r["all_three_lower_bounds_strictly_above_two"])
    def test_median_averages_middle_ratios_not_pooled_counts(self):
        pairs=[[n,1] for n in range(1,13)]
        self.assertEqual(c.distribution(pairs)["median"],[13,2])
        self.assertEqual(c.distribution(pairs)["rank2"],[2,1]);self.assertEqual(c.distribution(pairs)["rank11"],[11,1])
    def test_all_twelve_orders_and_native_source(self):
        original=sample()
        for what in ("missing","extra","wrong-order","two-01","missing-repair","bad-hardware","different-source","wrong-pilot","prior-run"):
            rows=copy.deepcopy(original);run=RUN
            if what=="missing":del rows["12"]
            if what=="extra":rows["13"]=rows["12"]
            if what=="wrong-order":rows["04"]["order"]=c.order("03")
            if what=="two-01":rows["02"]["boot"]=rows["02"]["calibration"]["boot"]=rows["01"]["boot"]
            if what=="missing-repair":del rows["02"]["observations"]["Fon"]["repair"]
            if what=="bad-hardware":rows["03"]["calibration"]["cpu"]="different"
            if what=="different-source":rows["01"]["head"]="3"*40
            if what=="wrong-pilot":rows["01"]["screen"]="0"*64
            if what=="prior-run":run=c.SCREEN["run"]
            with self.subTest(what=what),self.assertRaises(ValueError):c.summarize(rows,run,HEAD)
        self.assertEqual(sum(c.order(p)==c.ARMS for p in c.POSITIONS),6)
    def test_all_41_previous_boots_and_raw_counter(self):
        rows=sample()
        prior=json.loads((HERE/"excluded-boots.json").read_bytes());self.assertEqual(len(prior),41)
        for boot in prior:
            r=copy.deepcopy(rows);r["05"]["boot"]=r["05"]["calibration"]["boot"]=boot
            with self.assertRaises(ValueError):c.summarize(r,RUN,HEAD)
        for setting in ({"running":994},{"instructions":True},{"code":0},{"event_errno":13}):
            r=copy.deepcopy(rows);r["01"]["observations"]["Fon"]["invalid"]["raw_clock"].update(setting)
            with self.assertRaises(ValueError):c.summarize(r,RUN,HEAD)
    def test_different_pilot_archive(self):
        with self.assertRaises(ValueError):c.screen_original(io.BytesIO(b"wrong archive"),"01")

    def test_public_score_command_requires_original_job_archive_and_native_readback(self):
        workers=sample();receipts={};jobs={custody.PREFLIGHT:{"conclusion":"success"}};archives={}
        for pos,w in workers.items():
            label=custody.LABEL+pos;name=custody.ARTIFACT+pos
            jobs[label]={"id":50+int(pos),"name":label,"conclusion":"success"}
            archives[name]={"name":name,"id":100+int(pos),"size_in_bytes":999,"digest":"sha256:"+pos*32}
            receipts[pos]={"conclusion":"success","run":RUN,"head":HEAD,"position":pos,"job":jobs[label]["id"],"job_name":label,
                           "boot":w["boot"],"archive":archives[name],"worker_sha256":c.sha(custody.encoded(w)),"empty_native_sha256":c.sha(b"{}")}
        terminal={"run":{"status":"completed","conclusion":"success","id":RUN,"head_sha":HEAD},"jobs":jobs,"artifacts":archives}
        with tempfile.TemporaryDirectory() as tmp:
            q=Path(tmp)
            for pos in c.POSITIONS:
                (q/f"worker-{pos}.json").write_bytes(custody.encoded(workers[pos]));(q/f"receipt-{pos}.json").write_bytes(custody.encoded(receipts[pos]));(q/f"empty-native-{pos}.json").write_bytes(b"{}")
            (q/"terminal-catalog.json").write_bytes(custody.encoded(terminal))
            args=[sys.executable,"-IB",HERE/"confirmation.py","score","--run",str(RUN),"--head",HEAD,q]
            self.assertTrue(json.loads(subprocess.check_output(args,cwd=q))["all_three_lower_bounds_strictly_above_two"])
            (q/"empty-native-05.json").write_bytes(b"substituted")
            self.assertNotEqual(subprocess.run(args,cwd=q,capture_output=True).returncode,0)
        altered=copy.deepcopy(receipts);altered["03"]["archive"]["id"]+=1
        with self.assertRaises(ValueError):custody.check_result(workers,altered,terminal,RUN,HEAD)
        terminal["run"]["conclusion"]="failure"
        with self.assertRaises(ValueError):custody.check_result(workers,receipts,terminal,RUN,HEAD)

if __name__=="__main__":unittest.main()
