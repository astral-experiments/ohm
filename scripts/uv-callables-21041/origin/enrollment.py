"""Lock the independent production sources, the prospective case and the actual previous pilot."""
from hashlib import sha256
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent
P = "ac67101cb973e35ce8ff044cc8014c2c76bab69e"
C = "e4edbdd943f2ceac098ddde880e8f97a3bb3270f"
P_TREE = "1c07367341a9cc53272e9eefdae1ac8823d44839"
C_TREE = "8fdc0aa6f4833c25814f97056ed639212e53b6d5"
PROTOCOL = "d6f293599dceb1079fbf3ba6b534b2a263824210278c009773c3367b79fc7aa8"
INITIAL = "44e8f149aaae0ce310fc90422d8d8394d17bb59764911baec6b6cba3e8711177"
PLAN = "8cf21e82353a250ba861380b3c677b6ce42eedabb792273d1aa9b2d9255e1148"
SDK = "b68ee5229ac063c8178463015f1e259d334b89d46181f08207265cf45086ef14"
PACK = "d4dcc58f20f2029fbe7f796ff64370338589033fde267e9b2cc482970903f7e2"
CARGO = "3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871"
P_ROLE = "callables_ctfe318_incoherent_domain_proc_derive"
ROLES = [P_ROLE, P_ROLE + "_trait_origin"]
SOURCES = [P, C]
FORMATS = {"incremental": [43319, 43323], "metadata": [43319, 43319]}
sha = lambda path: sha256(path.read_bytes()).hexdigest()
read = lambda path: json.loads(path.read_bytes())

def source_gate():
    plan_path = HERE.parent/"measurement-plan.json"
    plan = read(plan_path)
    require(sha(plan_path) == PLAN and sha(HERE/"protocol.json") == PROTOCOL, "changed preregistration")
    require(plan["candidate_eligible_now"] is False and plan["control"]["commit"] == P and plan["roles"] == ROLES, "wrong prospectively enrolled pair")
    require(len(plan["known_boots"]) == 20 and plan["format_versions"] == FORMATS and plan["fixed_signed_cargo"] == CARGO, "source or prior machine authority")
    source = read(HERE/"source.json")
    require(source["role"] == ROLES[1] and source["source"]["commit"] == C and source["source"]["tree"] == C_TREE, "wrong private production child")
    require(source["format_versions"] == FORMATS and source["source"]["parent"] == P and source["source"]["parent_tree"] == P_TREE, "wrong private production parent")
    require(source["pack_sha256"] == PACK and source["pack_objects"] == 24 and source["pack_bytes"] == 93297, "not the sealed eight-path source change")
    return plan

def require(value, reason):
    if not value:
        raise ValueError(reason)

def pilot(pilot, controls):
    plan = source_gate()
    require(pilot["qualified_actual_capture"] is True and pilot["protocol"] == PROTOCOL and pilot["fixed_cargo"] == CARGO and pilot["registration"]==INITIAL==sha(HERE/"initial-v2.json"), "initial native guest pilot did not qualify")
    require(pilot["order"]==["parent-1","candidate-1","candidate-2","parent-2"] and [r["hold"] for r in pilot["holds"]]==[1,2], "unregistered initial order or omitted hold")
    require(pilot["uv"]["A"] == plan["input"]["A"] and pilot["uv"]["B"] == plan["input"]["B"] and pilot["uv"]["patch_sha256"] == plan["input"]["patch_sha256"], "wrong real edit")
    for key, commit, tree, epoch, driver in zip(("parent","candidate"),SOURCES,(P_TREE,C_TREE),(43319,43323),controls,strict=True):
        row=pilot["sources"][key]
        require((row["commit"],row["tree"],row["incremental_epoch"],row["rmeta_epoch"],row["driver"]) == (commit,tree,epoch,43319,driver), "initial pilot used another source or driver")
    require(len(pilot["holds"]) == 2, "missing one independent native history")
    values=[];named=[]
    for row in pilot["holds"]:
        counts=row["counts"];crates=plan["checked_compiler_instructions"]
        require(set(counts) == {*crates,"sum"}, "initial native pilot not all eight rustcs")
        for arm in ("parent","candidate"):
            require(all(type(counts[k][arm]) is int and counts[k][arm] > 0 for k in crates),"invalid guest count")
            require(counts["sum"][arm] == sum(counts[c][arm] for c in crates), "guest total disagrees with individual owners")
        values.append(1000*counts["sum"]["candidate"] < 996*counts["sum"]["parent"])
        named.append(5*counts["uv_metadata"]["candidate"] < 4*counts["uv_metadata"]["parent"])
        require(set(row["native_receipts"])=={"parent","candidate"} and set(row["cross_source_37"])=={"unchanged-a","first-b","cold-b-samepath"},"missing actual named native controls")
    cold={state:all(100*r["cold_terminal_Ir"][state]["candidate"]>102*r["cold_terminal_Ir"][state]["parent"] for r in pilot["holds"])for state in ("A","B")}
    verdict=pilot["decision"]
    require(verdict["both_sum_improve_0p40"]==all(values) and verdict["uv_metadata_20pct_both"]==all(named) and verdict["cold_by_state"]==cold
            and (all(values) or all(named)) and not any(cold.values()) and verdict["repeated_cold_regression"] is False and verdict["recommend_hardware"] is True,
            "initial screen does not authorize a fresh hardware benchmark")

def admit(study, pair):
    plan=source_gate()
    require(pair.get("enrolled") is True, "no candidate SDK or initial screened study enrolled")
    require(study["roles"] == pair["roles"] == ROLES and pair["format_versions"] == FORMATS and pair["protocol_sha256"] == PROTOCOL,"wrong pair")
    require(study["measurement_plan_sha256"] == pair["measurement_plan_sha256"] == PLAN and study["sdk_lock_sha256"] == sha(HERE.parent/"pair.json"),"wrong closed study")
    require(study["orders"] == [[ROLES[int(letter=="C")] for letter in x] for x in plan["pair_design"]["order"]]
            and study["mode_orders"] == plan["pair_design"]["mode_order"] and study["independent_holds"] == plan["pair_design"]["half"], "post-registration ordering change")
    require(all(pair["prior_boots"].get(k)==v for k,v in plan["known_boots"].items()), "lost registered boot")
    require(len(pair["prior_boots"]) == len({r["boot"] for r in pair["prior_boots"].values()}), "prior boot aliases")
    for role, commit, tree, inc in zip(ROLES,SOURCES,(P_TREE,C_TREE),(43319,43323),strict=True):
        a=pair["arms"][role]
        require((a["source"]["commit"],a["source"]["tree"],a["source"]["epoch"],a["source"]["metadata_epoch"])==(commit,tree,inc,43319),"different release source")
    require(sha(HERE/"pilot.json") == pair["initial_screen_sha256"],"different initial pilot")
    initial = read(HERE/"pilot.json")
    pilot(initial,[pair["arms"][role]["driver"] for role in ROLES])
    for key, role in zip(("parent","candidate"),ROLES,strict=True):
        require(initial["sources"][key]["installed_receipt"]==pair["arms"][role]["initial_sdk_enrollment"],"initial SDK custody differs")
    admitted_child(pair["arms"][ROLES[1]])

def admitted_child(child):
    seal = HERE/"candidate-native.json"
    require(sha(seal)=="65576fdf5a98f0efdd924c4aa437863276a3069fb995336a7bd269828885c378","different native production SDK proof")
    sdk=read(seal)
    require(sdk["members"]==142 and sdk["native_cargo"]==CARGO and sdk["initial_hardware_eligible"] is False,"invalid native SDK admission")
    require(child["service"]==sdk["original_service"] and child["driver"]==sdk["driver"] and child["source"]==sdk["source"],"wrong qualified service, driver or release source")
    require(all(child[k]==v for k,v in sdk["body_and_layout_evidence"].items()) and child["initial_sdk_enrollment"]==sdk["initial_candidate_sdk"]
            and child["installed_sdk_receipt"]==sdk["physical_installed_receipt"] and child["native_registration_sha256"]==sdk["native_registration"],
            "a new role would change independently calibrated inputs")
