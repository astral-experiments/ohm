"""Classify repeatability on the same source and retain independently decodable native objects."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import content

PHASES = ("typed-A", "ordinary-A", "ordinary-A-independent", "typed-warm-B", "typed-cold-B",
          "ordinary-cold-B", "ordinary-warm-B", "keyed-A", "keyed-warm-B", "keyed-cold-B")
TYPED = ("typed-A", "typed-warm-B", "typed-cold-B", "keyed-A", "keyed-warm-B", "keyed-cold-B")
KEYED = TYPED[3:]
PLAIN = ("ordinary-A", "ordinary-A-independent", "ordinary-warm-B", "ordinary-cold-B")
PAIRS = {
    "cold-A-plain-repeat": ("ordinary-A", "ordinary-A-independent"),
    "cold-A-typed-versus-plain-1": ("typed-A", "ordinary-A"),
    "cold-A-typed-versus-plain-2": ("typed-A", "ordinary-A-independent"),
    "cold-A-keyed-versus-typed": ("keyed-A", "typed-A"),
    "cold-A-keyed-versus-plain-1": ("keyed-A", "ordinary-A"),
    "cold-A-keyed-versus-plain-2": ("keyed-A", "ordinary-A-independent"),
    "warm-versus-cold-B-plain": ("ordinary-warm-B", "ordinary-cold-B"),
    "warm-versus-cold-B-typed": ("typed-warm-B", "typed-cold-B"),
    "warm-versus-cold-B-keyed": ("keyed-warm-B", "keyed-cold-B"),
    "warm-B-typed-versus-plain": ("typed-warm-B", "ordinary-warm-B"),
    "cold-B-typed-versus-plain": ("typed-cold-B", "ordinary-cold-B"),
    "warm-B-keyed-versus-typed": ("keyed-warm-B", "typed-warm-B"),
    "cold-B-keyed-versus-typed": ("keyed-cold-B", "typed-cold-B"),
    "warm-B-keyed-versus-plain": ("keyed-warm-B", "ordinary-warm-B"),
    "cold-B-keyed-versus-plain": ("keyed-cold-B", "ordinary-cold-B"),
}


def roots(capture, out):
    result = {}
    wanted = {}
    for snap in capture.material.values():
        for name, item in snap["rmeta"].items():
            wanted.setdefault(item["sha256"], (name, item))
    s = capture.s
    dest = out / "native-metadata-roots"
    dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=s.work) as scratch:
        for key, (name, item) in sorted(wanted.items()):
            path = Path(scratch) / Path(name).name
            try:
                path.write_bytes(capture.store.read(item))
                p = subprocess.run([s.rustc, "-Zls=root", path], env={"PATH": "/usr/bin:/bin", "LD_LIBRARY_PATH": str(s.rustc.parent.parent / "lib"),
                              "RUSTC_BOOTSTRAP": "1", "LC_ALL": "C"}, cwd=s.work, capture_output=True, timeout=60)
                (dest / (key + ".stdout")).write_bytes(p.stdout)
                (dest / (key + ".stderr")).write_bytes(p.stderr)
                content.require(p.returncode == 0, ("-Zls=root", p.returncode))
                fields = parse_root(p.stdout, path.name)
                result[key] = {"decoded": True, **fields, "stdout_sha256": content.digest(p.stdout), "stderr_sha256": content.digest(p.stderr)}
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                result[key] = {"decoded": False, "error": str(error)[:550]}
            finally:
                path.unlink(missing_ok=True)
    content.save(dest / "index.json", result)
    return result


def parse_root(data, filename):
    name, = re.findall(rb"^name ([A-Za-z0-9_]+-[0-9a-f]{16})$", data, re.M)
    (private, sid), = re.findall(rb"^private hash ([0-9a-f]{32}) stable_crate_id StableCrateId\(([0-9]+)\)$", data, re.M)
    public, = re.findall(rb"^public_hash ([0-9a-f]{32})$", data, re.M)
    content.require(private and sid and filename == "lib" + name.decode() + ".rmeta" and
                    data.count(b"=External Dependencies=\n") == 1, "unexpected native root/layout")
    deps = re.findall(rb"^\d+ \S+ hash [^\n]+$", data.partition(b"=External Dependencies=\n")[2], re.M)
    return {"private_hash": private.decode(), "public_hash": public.decode(), "stable_crate_id": int(sid),
            "dependencies": len(deps), "dependency_rows_sha256": content.digest(b"\n".join(deps))}


def reduce(capture, out):
    status, mats, forms, progress = capture.status, capture.material, capture.forms, capture.progress
    pair_results = {}
    store_verified = True
    try:
        for item in capture.store.items.values():
            capture.store.read(item)
    except (OSError, ValueError):
        store_verified = False
    native = roots(capture, out)
    for label, (a, b) in PAIRS.items():
        if a not in mats or b not in mats:
            pair_results[label] = {"available": False, "cohorts": [a, b]}
            continue
        row = content.compare(mats[a], mats[b], capture.store)
        for path, r in row["products"].items():
            if "sha256" not in r:
                continue
            x, y = [native.get(k, {}) for k in r["sha256"]]
            if x.get("decoded") and y.get("decoded"):
                r["native_root_fields_equal"] = {key: x[key] == y[key] for key in
                    ("private_hash", "public_hash", "stable_crate_id", "dependencies", "dependency_rows_sha256", "stdout_sha256")}
        content.save(out / "comparisons" / (label + ".json"), {"cohorts": [a, b], **row})
        diffs = sorted(k for k, product in row["products"].items() if not product["equal"])
        pair_results[label] = {"available": True, "cohorts": [a, b], "all_51_present": row["both_have_all_51"],
                               "all_51_byte_equal": row["full_rmeta_byte_equality"], "different": diffs,
                               "all_sidecars_equal": row["sidecar_sets_equal"] and not row["sidecar_raw_differences"]}
    classic = {}
    for state in ("A", "warm-B", "cold-B"):
        left, right = forms.get("typed-" + state), forms.get("keyed-" + state)
        if left and right:
            classic[state] = {"units": left["units"] == right["units"], "workspace_rmeta": left["workspace_rmeta"] == right["workspace_rmeta"],
                              "workspace_diagnostics": left["workspace_diagnostics"] == right["workspace_diagnostics"],
                              "all_original_rustcs": sorted(left["rustcs"]) == sorted(right["rustcs"]),
                              "same_selected_argv": left["argv"] == right["argv"],
                              "only_selected_extra_flags": right.get("executed_argv") == left["argv"] + [
                                  "-Zself-profile=" + str(capture.s.keys), "-Zself-profile-events=" + capture.base_profile]}
        else:
            classic[state] = {"available": False}
    def retained(label, *ops):
        return all(status.get(label, {}).get(op, {}).get("pass") is True for op in ops)
    required = (store_verified and all(retained(n, "positive_compile", "material", "native_progress") for n in PHASES) and
                all(retained(n, "graph") for n in PLAIN + KEYED) and all(retained(n, "every_dirty_rustc") for n in TYPED) and
                all(retained(n, "profile", "selected_executed_argv") for n in KEYED) and
                retained("ordinary-A", "checkpoint", "unchanged_checkpoint") and
                all(retained(n, "restore") for n in ("typed-warm-B", "ordinary-warm-B")))
    passed = all(retained(n, "positive_compile", "native_metadata_witness") for n in PHASES) and all(
                retained(n, "upstream_behavior") for n in ("typed-A", "typed-warm-B", "typed-cold-B"))
    historical = {}
    for name in sorted(capture.paths):
        prior = [capture.prior["cold_typed_A"][name][1], capture.prior["cold_plain_A"][name][1]]
        rows = {}
        for phase in ("typed-A", "ordinary-A", "ordinary-A-independent", "keyed-A"):
            if name in mats.get(phase, {}).get("rmeta", {}):
                sha = mats[phase]["rmeta"][name]["sha256"]
                rows[phase] = {"sha256": sha, "matches_prior_typed": sha == prior[0], "matches_prior_plain": sha == prior[1]}
        historical[name] = {"prior_cold_typed_and_plain": prior, "current": rows}
    content.save(out / "historical-A-products.json", historical)
    def form_comparison(a, b):
        if a not in forms or b not in forms:
            return {"available": False}
        return {k: forms[a][k] == forms[b][k] for k in ("units", "workspace_rmeta", "workspace_diagnostics", "argv")}
    def change(a, b):
        if a not in mats or b not in mats:
            return None
        found = [n for n in capture.paths if Path(n).name.startswith("libuv_distribution_types-")]
        if len(found) != 1 or any(found[0] not in mats[x]["rmeta"] for x in (a, b)):
            return None
        return mats[a]["rmeta"][found[0]]["sha256"] != mats[b]["rmeta"][found[0]]["sha256"]
    complete_bytes = all(v.get("all_51_present") and v.get("all_51_byte_equal") for v in pair_results.values())
    content.save(out / "object-index.json", capture.store.items)
    return {"schema": 1, "diagnostic_only": True, "performance_eligible": False,
            "required_evidence_captured": bool(required), "scoped_compilations_and_witnesses_pass": bool(passed),
            "store_verified_after_collection": store_verified, "content_addressed_objects": len(capture.store.items), "compressed_object_bytes": capture.store.total,
            "all_native_metadata_roots_decoded": len(native) > 0 and all(v.get("decoded") for v in native.values()),
            "full_raw_product_equality_all_same_revision_comparisons": complete_bytes,
            "same_revision_comparisons": pair_results, "typed_keyed_full_alignment": classic,
            "ordinary_warm_versus_cold_typed": form_comparison("typed-warm-B", "typed-cold-B"),
            "keyed_warm_versus_cold": form_comparison("keyed-warm-B", "keyed-cold-B"),
            "same_cargo_units_across_edit": forms["typed-A"]["units"] == forms["typed-warm-B"]["units"] if "typed-A" in forms and "typed-warm-B" in forms else None,
            "all_available_dirty_progress_equality": {tag: progress[a] == progress[b] if a in progress and b in progress else None for tag, (a, b) in PAIRS.items()},
            "warm_dirty_plain_versus_typed": progress.get("ordinary-warm-B") == progress.get("typed-warm-B") if "ordinary-warm-B" in progress and "typed-warm-B" in progress else None,
            "defining_crate_changes_A_to_B": {a: change(a, b) for a, b in (("ordinary-A","ordinary-warm-B"),("typed-A","typed-warm-B"),("keyed-A","keyed-warm-B"))},
            "profile_graph_scope": "Forensics only, irrespective of equality. A prior direct read or evaluation does not establish a first veto.",
            "plain_child_argv": "Pure Cargo does not print rustc argv. Its graph is bound through same-phase actual verbose argv and its own live target rmeta."}
