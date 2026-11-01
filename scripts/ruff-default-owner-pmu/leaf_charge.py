"""Project selected signed compiler leaves; keyed by (package,target,kind), never inferred from PID count."""

from collections import Counter
import re
import leaf_events as raw

# Stable names remove only rustc's demangled crate hash. General utility code is never assigned to callers.
PHASES = (
    ("incremental graph", r"rustc_(?:middle::dep_graph|query_system::dep_graph|dep_graph)::"),
    ("incremental persistence", r"rustc_(?:incremental::|query_impl::(?:on_disk_cache|plumbing::on_disk)::)"),
    ("metadata encode", r"rustc_metadata::rmeta::encoder::"),
    ("metadata decode", r"rustc_metadata::(?:rmeta::decoder|creader|locator)::"),
    ("parse/expansion/resolution", r"rustc_(?:parse|expand|resolve|ast_lowering)::"),
    (
        "type/trait/borrow analysis",
        r"rustc_(?:hir_typeck|trait_selection|next_trait_solver|borrowck|hir_analysis|infer)::",
    ),
    ("MIR construction and transforms", r"rustc_(?:mir_build|mir_transform|mir_dataflow)::"),
    ("monomorphization/partition", r"rustc_monomorphize::"),
    ("Rust code generation", r"rustc_(?:codegen_ssa|codegen_llvm|codegen_gcc)::"),
    ("stable hashing infrastructure", r"rustc_(?:stable_hash|data_structures::stable_hasher)::"),
    ("query dispatch infrastructure", r"rustc_query_(?:impl|system)::"),
)


def category(llvm, image, symbol):
    if image == llvm:
        return "LLVM DSO — uniquely resolved native function"
    s = re.sub(r"\[[0-9a-f]{4,32}\]", "", symbol)
    # For a trait method one cannot establish an execution phase from the type argument.
    if s.startswith("<"):
        if not s.split(">::", 1)[0].endswith(">") and " as " not in s.split(">::", 1)[0]:
            s = s[1:]
        else:
            return "other signed function"
    for cls, pattern in PHASES:
        if re.match(pattern, s):
            return cls
    return "other signed function"


def charge(records, owner, enrolled, symbols, demangle, llvm):
    """The caller authenticates package/argv/starttime and original rustc map path & census."""
    rows, maps, execs, forks, exits, _ = records
    subset, pmap = raw.epochs(rows, maps, execs, forks, exits, owner["pid"], owner["actual_image"])
    raw.require(bool(subset), "selected physical owner had zero accepted samples")
    roles = Counter()
    fns = Counter()
    per_thread = Counter()
    for row in subset:
        family, off = raw.named_mapping(row, pmap, enrolled)
        weight = row[4]
        per_thread[row[2]] += weight
        if off is None:
            roles[family] += weight
            continue
        names = symbols[family].resolve(off)
        if len(names) != 1:
            roles["ambiguous or no sized function"] += weight
            continue
        fns[family, next(iter(names))] += weight
    converted = demangle({n for _, n in fns}) if fns else {}
    for (im, s), v in fns.items():
        roles[category(llvm, im, converted[s])] += v
    total = sum(r[4] for r in subset)
    raw.require(total == sum(roles.values()), "non-disjoint classification")
    return {
        "key": owner["key"],
        "pid": owner["pid"],
        "sampled_tids": sorted(per_thread),
        "sample_weight_by_tid": {str(k): v for k, v in sorted(per_thread.items())},
        "samples": len(subset),
        "weighted_observations": total,
        "physical_sized_functions_weight": sum(fns.values()),
        "phase": dict(roles),
        "named": [[im, converted[s], n] for (im, s), n in fns.most_common()],
    }


def cohort(rows, full_owner_census, wanted):
    """A named subset projects a single registered whole command; its denominator stays unchanged."""
    keys = {r["key"] for r in full_owner_census}
    raw.require(
        len(keys) == len(full_owner_census) and len({r["pid"] for r in full_owner_census}) == len(keys),
        "ambiguous full owner census",
    )
    raw.require(wanted <= keys and bool(wanted), "absent registered owner")
    chosen = [r for r in rows if r["key"] in wanted]
    raw.require(
        len(chosen) == len(wanted) and {r["key"] for r in chosen} == wanted,
        "missing or duplicated selected physical owner",
    )
    numer = Counter()
    for r in chosen:
        raw.require(
            next(x["pid"] for x in full_owner_census if x["key"] == r["key"]) == r["pid"],
            "mismatched sealed owner PID",
        )
        numer.update(r["phase"])
    raw.require(
        sum(numer.values()) == sum(r["weighted_observations"] for r in chosen), "cohort reconciliation"
    )
    return dict(numer)
