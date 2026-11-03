"""Authenticate the dispatch input supplied by the Actions event and the immutable rank plan."""
import json
import os
from pathlib import Path

SPEC=json.loads((Path(__file__).parent/"confirmation.json").read_bytes())

def registration(rank):
    if type(rank) is not int or not 0<=rank<len(SPEC["ranks"]):
        raise ValueError("unregistered confirmation rank")
    return dict(rank=rank,order=list(SPEC["ranks"][rank]),spec=SPEC)

def enrollment():
    rank=os.environ["CONFIRMATION_RANK"]
    ev=json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    if not rank.isascii()or not rank.isdigit() or ev["inputs"]!={"rank":rank,"reviewed_head":os.environ["REVIEWED_HEAD"]}:
        raise ValueError("different original dispatched rank or head")
    return registration(int(rank))
