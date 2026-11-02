"""Assign a preregistered compiler order to each independent worker."""
import os


def assigned():
    mode = os.environ["OHM_STUDY"]
    rank = int(os.environ["OHM_OBSERVATION"])
    if mode == "ruff" and rank == 0:
        return ("PC", "CP")
    if mode == "ruff-confirm" and 0 <= rank < 6:
        return (("PC", "CP")[rank % 2],)
    raise ValueError("Unregistered study mode or observation")
