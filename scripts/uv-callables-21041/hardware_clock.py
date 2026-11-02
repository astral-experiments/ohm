from pathlib import Path
import os,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import core as c,wall_clock
w,tmp=c.host();out=w/'trait-results';cal=c.m.read(out/'calibration.json')['ready'];mask=set(cal['affinity']);assert mask<=os.sched_getaffinity(0);os.sched_setaffinity(0,mask)
wall_clock.calibrate(out/'blocking-clock',tmp/'validated-wall-probe')
