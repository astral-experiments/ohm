#![feature(rustc_private)]

extern crate rustc_ast;
extern crate rustc_driver;
extern crate rustc_hir;
extern crate rustc_interface;
extern crate rustc_middle;

use std::collections::{BTreeMap, HashSet, VecDeque};
use std::sync::{Mutex, OnceLock};

use rustc_ast::{LitIntType, LitKind, UintTy};
use rustc_driver::{Callbacks, Compilation};
use rustc_hir::def::DefKind;
use rustc_hir::def_id::LocalDefId;
use rustc_hir::{ImplItemKind, OwnerId, OwnerNode};
use rustc_interface::interface;
use rustc_middle::queries;
use rustc_middle::query::resident::ResidentQueryKey;
use rustc_middle::ty::TyCtxt;

type TypeProvider =
    for<'tcx> fn(TyCtxt<'tcx>, LocalDefId) -> queries::typeck_root::ProvidedValue<'tcx>;
type BorrowProvider =
    for<'tcx> fn(TyCtxt<'tcx>, LocalDefId) -> queries::mir_borrowck::ProvidedValue<'tcx>;
static TYPE: OnceLock<TypeProvider> = OnceLock::new();
static BORROW: OnceLock<BorrowProvider> = OnceLock::new();
static COUNTS: Mutex<BTreeMap<u32, [usize; 2]>> = Mutex::new(BTreeMap::new());

const SELECTED: &[&str] = &["is_unicode_identifier_start", "parse_octet"];
const CONTROLS: &[&str] = &[
    "strip_underscores",
    "is_known_future_feature",
    "is_identifier_continuation",
    "single_char_prefix",
];
const ADDITIONAL: &[&str] = &["is_complex_number"];

fn count(id: LocalDefId, slot: usize) {
    COUNTS
        .lock()
        .unwrap()
        .entry(id.local_def_index.as_u32())
        .or_default()[slot] += 1;
}

fn counted_type<'tcx>(
    tcx: TyCtxt<'tcx>,
    id: LocalDefId,
) -> queries::typeck_root::ProvidedValue<'tcx> {
    count(id, 0);
    TYPE.get().unwrap()(tcx, id)
}

fn counted_borrow<'tcx>(
    tcx: TyCtxt<'tcx>,
    id: LocalDefId,
) -> queries::mir_borrowck::ProvidedValue<'tcx> {
    count(id, 1);
    BORROW.get().unwrap()(tcx, id)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct State {
    type_count: usize,
    borrow_count: usize,
    pointer: usize,
    success: bool,
    borrow_demanded: bool,
}

fn demand(tcx: TyCtxt<'_>, id: LocalDefId) -> State {
    let ty = tcx.typeck(id);
    let borrow_demanded = ty.tainted_by_errors.is_none();
    let success = borrow_demanded && tcx.mir_borrowck(id).is_ok();
    let counts = COUNTS
        .lock()
        .unwrap()
        .get(&id.local_def_index.as_u32())
        .copied()
        .unwrap_or_default();
    State {
        type_count: counts[0],
        borrow_count: counts[1],
        pointer: ty as *const _ as usize,
        success,
        borrow_demanded,
    }
}

fn observe(
    tcx: TyCtxt<'_>,
    phase: &str,
    owners: &BTreeMap<String, LocalDefId>,
) -> BTreeMap<String, State> {
    let results: BTreeMap<_, _> = owners
        .iter()
        .map(|(name, &id)| (name.clone(), demand(tcx, id)))
        .collect();
    for (name, state) in &results {
        println!(
            "owner\t{phase}\t{name}\t{}\t{}\t{}\t{}\t{}\t{}",
            owners[name].local_def_index.as_u32(),
            state.type_count,
            state.borrow_count,
            state.pointer,
            state.success,
            state.borrow_demanded
        );
    }
    println!("errors\t{phase}\t{}", tcx.dcx().err_count());
    results
}

fn compare_controls(
    baseline: &BTreeMap<String, State>,
    current: &BTreeMap<String, State>,
    phase: &str,
) {
    for &name in CONTROLS.iter().chain(ADDITIONAL) {
        if baseline[name] != current[name] {
            eprintln!(
                "control-recomputed:{phase}:{name}:{:?}:{:?}",
                baseline[name], current[name]
            );
        }
    }
}

fn explain_extra_control(
    tcx: TyCtxt<'_>,
    selected: LocalDefId,
    selected_name: &str,
    extra: LocalDefId,
) {
    let graph = tcx.query_system.resident.as_ref().unwrap();
    let end = ResidentQueryKey::HirBody(selected);
    let affected: HashSet<_> = graph.affected([end]).into_iter().collect();
    let Some(start) = affected
        .iter()
        .copied()
        .find(|key| key.name() == "mir_borrowck" && key.def_id() == Some(extra.to_def_id()))
    else {
        println!("control-path\t{selected_name}\tnot in tracked reverse closure");
        return;
    };
    let mut queue = VecDeque::from([vec![start]]);
    let mut seen = HashSet::from([start]);
    while let Some(path) = queue.pop_front() {
        let tail = *path.last().unwrap();
        if tail == end {
            let formatted: Vec<_> = path.iter().map(|key| format!("{key:?}")).collect();
            println!("control-path\t{selected_name}\t{}", formatted.join(" -> "));
            return;
        }
        let mut dependencies = graph.dependencies(tail);
        dependencies.sort_by_key(|key| format!("{key:?}"));
        for dependency in dependencies {
            if affected.contains(&dependency) && seen.insert(dependency) {
                let mut next = path.clone();
                next.push(dependency);
                queue.push_back(next);
            }
        }
    }
    println!("control-path\t{selected_name}\tno recorded dependency path");
}

struct Driver;

impl Callbacks for Driver {
    fn config(&mut self, config: &mut interface::Config) {
        config.override_queries = Some(|_, providers| {
            TYPE.set(providers.queries.typeck_root).unwrap();
            BORROW.set(providers.queries.mir_borrowck).unwrap();
            providers.queries.typeck_root = counted_type;
            providers.queries.mir_borrowck = counted_borrow;
        });
    }

    fn after_expansion<'tcx>(&mut self, _: &interface::Compiler, tcx: TyCtxt<'tcx>) -> Compilation {
        assert!(tcx.query_system.resident.is_some());
        println!("context\t{}\t{:p}", std::process::id(), *tcx);
        let mut owners = BTreeMap::new();
        for id in tcx.hir_body_owners() {
            if !matches!(tcx.def_kind(id), DefKind::Fn | DefKind::AssocFn) {
                continue;
            }
            let name = tcx.item_name(id.to_def_id()).to_string();
            if SELECTED.contains(&name.as_str())
                || CONTROLS.contains(&name.as_str())
                || ADDITIONAL.contains(&name.as_str())
            {
                assert!(
                    owners.insert(name.clone(), id).is_none(),
                    "owner must be unique: {name}"
                );
                let path = rustc_middle::ty::print::with_no_trimmed_paths!(
                    tcx.def_path_str(id.to_def_id())
                );
                println!("identity\t{name}\t{}\t{path}", id.local_def_index.as_u32());
                if let OwnerNode::ImplItem(item) = tcx.hir_owner_node(OwnerId { def_id: id })
                    && let ImplItemKind::Fn(signature, _) = item.kind
                {
                    let params: Vec<_> = item
                        .generics
                        .params
                        .iter()
                        .map(|param| format!("{:?}:{:?}", param.name, param.kind))
                        .collect();
                    println!(
                        "classifier\t{name}\tasync={:?}\tparams={:?}\tpredicates={}\tvisibility={:?}\texpected={:?}",
                        signature.header.is_async(),
                        params,
                        item.generics.predicates.len(),
                        tcx.visibility(id),
                        rustc_middle::ty::Visibility::Restricted(
                            tcx.parent_module_from_def_id(id).to_def_id()
                        )
                    );
                }
            }
        }
        assert_eq!(
            owners.len(),
            SELECTED.len() + CONTROLS.len() + ADDITIONAL.len()
        );
        if std::env::var_os("OHM_RUFF_INSPECT_ONLY").is_some() {
            println!("complete\tinspect\tonly");
            return Compilation::Stop;
        }
        eprintln!("targeted-start:baseline");
        tcx.ensure_ok().analysis(());
        let baseline = observe(tcx, "baseline", &owners);
        assert_eq!(tcx.dcx().err_count(), 0);
        assert!(
            baseline
                .values()
                .all(|state| state.success && state.type_count >= 1 && state.borrow_count >= 1)
        );
        eprintln!("targeted-end:baseline");

        for &name in SELECTED {
            let id = owners[name];
            explain_extra_control(tcx, id, name, owners[ADDITIONAL[0]]);
            let mut previous = demand(tcx, id);
            for iteration in 1..=2 {
                let phase = format!("{name}:{iteration}:changed");
                tcx.dcx().reset_err_count();
                eprintln!("targeted-start:{phase}");
                let replacement = LitKind::Int(0u128.into(), LitIntType::Unsigned(UintTy::U8));
                let (snapshot, eviction) =
                    match unsafe { tcx.ohm_override_private_scalar_tail(id, replacement) } {
                        Ok(value) => value,
                        Err(reason) => panic!("{phase} not supported: {reason}"),
                    };
                println!(
                    "eviction\t{phase}\t{}\t{}\t{}\t{}",
                    eviction.revision,
                    eviction.removed.len(),
                    eviction.uncached.len(),
                    eviction.trait_solver_caches_reset
                );
                let current = observe(tcx, &phase, &owners);
                compare_controls(&baseline, &current, &phase);
                assert_eq!(tcx.dcx().err_count(), 1, "one real error in {phase}");
                assert!(
                    !current[name].success && !current[name].borrow_demanded,
                    "type must fail in {phase}"
                );
                assert!(
                    current[name].type_count > previous.type_count
                        && current[name].pointer != previous.pointer,
                    "selected type check must rerun in {phase}"
                );
                previous = current[name];
                eprintln!("targeted-end:{phase}");

                let phase = format!("{name}:{iteration}:restored");
                tcx.dcx().reset_err_count();
                eprintln!("targeted-start:{phase}");
                let eviction = match unsafe { tcx.ohm_restore_private_scalar_tail(snapshot) } {
                    Ok(value) => value,
                    Err(reason) => panic!("{phase} not supported: {reason}"),
                };
                println!(
                    "eviction\t{phase}\t{}\t{}\t{}\t{}",
                    eviction.revision,
                    eviction.removed.len(),
                    eviction.uncached.len(),
                    eviction.trait_solver_caches_reset
                );
                let current = observe(tcx, &phase, &owners);
                compare_controls(&baseline, &current, &phase);
                assert_eq!(tcx.dcx().err_count(), 0, "restoration must clear {phase}");
                assert!(
                    current.values().all(|state| state.success),
                    "all selected and control roots must be clean again for {phase}"
                );
                assert!(
                    current[name].type_count > previous.type_count
                        && current[name].pointer != previous.pointer
                        && current[name].borrow_count > previous.borrow_count,
                    "selected type and borrow must rerun in {phase}"
                );
                previous = current[name];
                eprintln!("targeted-end:{phase}");
            }
        }
        tcx.dcx().reset_err_count();
        println!("complete\t{}\t{}", SELECTED.len(), CONTROLS.len());
        Compilation::Stop
    }
}

fn main() -> std::process::ExitCode {
    let args = std::env::args().collect::<Vec<_>>();
    rustc_driver::catch_with_exit_code(|| rustc_driver::run_compiler(&args, &mut Driver))
}
