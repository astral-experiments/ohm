"""Require a different from-empty A target for every role in every paired first edit."""
from re import fullmatch

def enroll(seen, receipt, pair, role):
    if set(receipt)!={"count","hold","role","sha256"}:
        raise ValueError("incomplete native A checkpoint identity")
    key=receipt["sha256"]
    if (type(pair) is not int or pair not in range(8) or receipt["hold"]!=pair or receipt["role"]!=role or
        type(receipt["count"]) is not int or receipt["count"]<=0 or not fullmatch("[0-9a-f]{64}",key) or key in seen):
        raise ValueError("reused, mispaired or empty native A checkpoint")
    seen.add(key)
    return key
