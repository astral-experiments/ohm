#![feature(rustc_private)]

extern crate rustc_ast;
extern crate rustc_driver;
extern crate rustc_hir;
extern crate rustc_interface;
extern crate rustc_lexer;
extern crate rustc_middle;
extern crate rustc_parse;
extern crate rustc_session;
extern crate rustc_span;

use std::collections::{BTreeMap, BTreeSet};
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use rustc_ast::{ExprKind as AstExprKind, LitKind, token};
use rustc_driver::{Callbacks, Compilation};
use rustc_hir::ExprKind;
use rustc_hir::def::DefKind;
use rustc_hir::def_id::LocalDefId;
use rustc_interface::{Linker, interface, passes};
use rustc_lexer::{FrontmatterAllowed, TokenKind};
use rustc_middle::hir::map::OhmResidentScalarTailSnapshot;
use rustc_middle::ty::TyCtxt;
use rustc_parse::lexer::StripTokens;
use rustc_session::parse::ParseSess;
use rustc_span::FileName;

fn stdout(line: std::fmt::Arguments<'_>) {
    let mut stream = io::stdout().lock();
    writeln!(stream, "{line}").unwrap();
    stream.flush().unwrap();
}

fn marker(phase: &str, version: &str) {
    let mut stream = io::stderr().lock();
    writeln!(stream, "source-{phase}\t{version}").unwrap();
    stream.flush().unwrap();
}

#[derive(Clone, Copy)]
struct Lexeme {
    kind: TokenKind,
    start: usize,
    end: usize,
}

fn tokenize(source: &str) -> Vec<Lexeme> {
    let mut offset = 0;
    rustc_lexer::tokenize(source, FrontmatterAllowed::No)
        .filter_map(|token| {
            let start = offset;
            offset += token.len as usize;
            if matches!(
                token.kind,
                TokenKind::Whitespace
                    | TokenKind::LineComment { doc_style: None }
                    | TokenKind::BlockComment {
                        doc_style: None,
                        terminated: true,
                    }
            ) {
                None
            } else {
                Some(Lexeme {
                    kind: token.kind,
                    start,
                    end: offset,
                })
            }
        })
        .collect()
}

fn token_identifier(token: Lexeme, source: &str) -> Option<&str> {
    if !matches!(token.kind, TokenKind::Ident | TokenKind::RawIdent) {
        return None;
    }
    let name = &source[token.start..token.end];
    let name = name.strip_prefix("r#").unwrap_or(name);
    match name {
        // A use tree can contain these, but a function tail cannot be using them as an
        // imported binding. In particular every method's `self` must not trip this guard.
        "as" | "crate" | "self" | "super" | "use" => None,
        _ => Some(name),
    }
}

fn names_in_use_trees(tokens: &[Lexeme], source: &str) -> BTreeSet<String> {
    let mut names = BTreeSet::new();
    let mut in_use = false;
    for &token in tokens {
        let spelling = &source[token.start..token.end];
        if token.kind == TokenKind::Ident && spelling == "use" {
            in_use = true;
        } else if in_use && spelling == ";" {
            in_use = false;
        } else if in_use && let Some(name) = token_identifier(token, source) {
            names.insert(name.to_owned());
        }
    }
    names
}

fn source_independent_macros(
    tokens: &[Lexeme],
    source: &str,
    imported_names: &BTreeSet<String>,
) -> bool {
    const KNOWN_MACROS: &[&str] = &["format", "matches", "vec"];
    const KNOWN_DERIVES: &[&str] = &[
        "Clone",
        "Copy",
        "Debug",
        "Default",
        "Eq",
        "Hash",
        "Ord",
        "PartialEq",
        "PartialOrd",
    ];
    for (index, pair) in tokens.windows(2).enumerate() {
        let [name_token, next] = pair else {
            unreachable!()
        };
        let Some(name) = token_identifier(*name_token, source) else {
            continue;
        };
        // Qualified names may resolve to user macros with standard-looking final segments.
        let qualified = index >= 2
            && tokens[index - 1].kind == TokenKind::Colon
            && tokens[index - 2].kind == TokenKind::Colon;
        let expression_keyword = name_token.kind == TokenKind::Ident
            && matches!(
                name,
                "if" | "while"
                    | "return"
                    | "let"
                    | "match"
                    | "else"
                    | "for"
                    | "in"
                    | "loop"
                    | "yield"
                    | "break"
                    | "continue"
                    | "const"
                    | "unsafe"
                    | "async"
                    | "move"
                    | "dyn"
            );
        let macro_delimiter = tokens.get(index + 2).is_some_and(|token| {
            matches!(
                token.kind,
                TokenKind::OpenParen | TokenKind::OpenBracket | TokenKind::OpenBrace
            )
        });
        if next.kind == TokenKind::Bang
            && macro_delimiter
            && !expression_keyword
            && (!KNOWN_MACROS.contains(&name)
                || imported_names.contains(name)
                || qualified
                || name_token.kind == TokenKind::RawIdent)
        {
            return false;
        }
        if matches!(name, "macro" | "macro_rules") && name_token.kind == TokenKind::Ident {
            return false;
        }
    }
    for (index, token) in tokens.iter().enumerate() {
        if token.kind != TokenKind::Pound {
            continue;
        }
        let mut cursor = index + 1;
        if tokens
            .get(cursor)
            .is_some_and(|token| token.kind == TokenKind::Bang)
        {
            cursor += 1;
        }
        if !tokens
            .get(cursor)
            .is_some_and(|token| token.kind == TokenKind::OpenBracket)
        {
            continue;
        }
        cursor += 1;
        let Some(name) = tokens
            .get(cursor)
            .and_then(|token| token_identifier(*token, source))
        else {
            return false;
        };
        if name == "derive" {
            for token in &tokens[cursor + 1..] {
                if token.kind == TokenKind::CloseBracket {
                    break;
                }
                if token.kind == TokenKind::Colon
                    || (token_identifier(*token, source).is_some_and(|name| {
                        !KNOWN_DERIVES.contains(&name) || imported_names.contains(name)
                    }))
                {
                    return false;
                }
            }
        } else if !matches!(
            name,
            "allow"
                | "cfg"
                | "cold"
                | "deny"
                | "deprecated"
                | "doc"
                | "expect"
                | "forbid"
                | "inline"
                | "must_use"
                | "non_exhaustive"
                | "repr"
                | "test"
                | "warn"
        ) {
            // In particular `cfg_attr` can hide an arbitrary procedural attribute.
            return false;
        }
    }
    true
}

fn raw_change(old: &str, new: &str) -> (usize, usize) {
    let old = old.as_bytes();
    let new = new.as_bytes();
    let prefix = old.iter().zip(new).take_while(|(a, b)| a == b).count();
    let suffix = old
        .iter()
        .rev()
        .zip(new.iter().rev())
        .take(old.len().min(new.len()) - prefix)
        .take_while(|(a, b)| a == b)
        .count();
    (prefix, old.len() - suffix)
}

fn token_equal(a: Lexeme, a_text: &str, b: Lexeme, b_text: &str) -> bool {
    a.kind == b.kind && a_text[a.start..a.end] == b_text[b.start..b.end]
}

fn common_tokens(old: &[Lexeme], old_text: &str, new: &[Lexeme], new_text: &str) -> (usize, usize) {
    let limit = old.len().min(new.len());
    let prefix = old
        .iter()
        .copied()
        .zip(new.iter().copied())
        .take_while(|&(a, b)| token_equal(a, old_text, b, new_text))
        .count();
    let suffix = old
        .iter()
        .rev()
        .copied()
        .zip(new.iter().rev().copied())
        .take(limit - prefix)
        .take_while(|&(a, b)| token_equal(a, old_text, b, new_text))
        .count();
    (prefix, suffix)
}

fn validate_file(session: &ParseSess, text: &str) -> bool {
    let result = rustc_parse::new_parser_from_source_str(
        session,
        FileName::Custom("resident-file".to_owned()),
        text.to_owned(),
        StripTokens::Nothing,
    );
    let mut parser = match result {
        Ok(parser) => parser,
        Err(errors) => {
            for error in errors {
                error.cancel();
            }
            return false;
        }
    };
    match parser.parse_crate_mod() {
        Ok(_) => session.dcx().has_errors().is_none(),
        Err(error) => {
            error.cancel();
            false
        }
    }
}

fn scalar(session: &ParseSess, text: &str) -> Option<LitKind> {
    let result = rustc_parse::new_parser_from_source_str(
        session,
        FileName::Custom("resident-expression".to_owned()),
        text.to_owned(),
        StripTokens::Nothing,
    );
    let mut parser = match result {
        Ok(parser) => parser,
        Err(errors) => {
            for error in errors {
                error.cancel();
            }
            return None;
        }
    };
    let expression = match parser.parse_expr() {
        Ok(expression) => expression,
        Err(error) => {
            error.cancel();
            return None;
        }
    };
    if parser.token.kind != token::Eof || session.dcx().has_errors().is_some() {
        return None;
    }
    let AstExprKind::Lit(literal) = expression.kind else {
        return None;
    };
    match LitKind::from_token_lit(literal).ok()? {
        literal @ (LitKind::Bool(_) | LitKind::Char(_) | LitKind::Int(..)) => Some(literal),
        _ => None,
    }
}

#[derive(Clone)]
struct Candidate {
    owner: LocalDefId,
    start: usize,
    end: usize,
    owner_start: usize,
    owner_end: usize,
    owner_first_token: usize,
    owner_end_token: usize,
    first_token: usize,
    end_token: usize,
}

struct FileState {
    baseline: String,
    baseline_tokens: Vec<Lexeme>,
    accepted: String,
    accepted_tokens: Vec<Lexeme>,
    imported_names: BTreeSet<String>,
    candidates: Vec<Candidate>,
}

fn files(tcx: TyCtxt<'_>) -> BTreeMap<PathBuf, FileState> {
    let mut files: BTreeMap<PathBuf, FileState> = BTreeMap::new();
    for owner in tcx.hir_body_owners() {
        if !matches!(tcx.def_kind(owner), DefKind::Fn | DefKind::AssocFn) {
            continue;
        }
        let body = tcx.hir_body_owned_by(owner);
        let ExprKind::Block(block, None) = body.value.kind else {
            continue;
        };
        let Some(tail) = block.expr else { continue };
        if tail.span.from_expansion() || !block.span.contains(tail.span) {
            continue;
        }
        let source_file = tcx.sess.source_map().lookup_source_file(tail.span.lo());
        let Some(filename) = source_file.name.clone().into_local_path() else {
            continue;
        };
        let Ok(path) = std::fs::canonicalize(filename) else {
            continue;
        };
        let Some(source) = &source_file.src else {
            continue;
        };
        let file = files.entry(path).or_insert_with(|| {
            let baseline = source.as_str().to_owned();
            let baseline_tokens = tokenize(&baseline);
            let imported_names = names_in_use_trees(&baseline_tokens, &baseline);
            FileState {
                accepted: baseline.clone(),
                accepted_tokens: baseline_tokens.clone(),
                baseline,
                baseline_tokens,
                imported_names,
                candidates: Vec::new(),
            }
        });
        let start = (tail.span.lo() - source_file.start_pos).0 as usize;
        let end = (tail.span.hi() - source_file.start_pos).0 as usize;
        let owner_span = tcx.hir_span_with_body(tcx.local_def_id_to_hir_id(owner));
        if owner_span.lo() < source_file.start_pos || owner_span.hi() > source_file.end_position() {
            continue;
        }
        let owner_start = (owner_span.lo() - source_file.start_pos).0 as usize;
        let owner_end = (owner_span.hi() - source_file.start_pos).0 as usize;
        let first_token = file
            .baseline_tokens
            .partition_point(|token| token.end <= start);
        let end_token = file
            .baseline_tokens
            .partition_point(|token| token.start < end);
        if first_token == end_token {
            continue;
        }
        let owner_first_token = file
            .baseline_tokens
            .partition_point(|token| token.end <= owner_start);
        let owner_end_token = file
            .baseline_tokens
            .partition_point(|token| token.start < owner_end);
        file.candidates.push(Candidate {
            owner,
            start,
            end,
            owner_start,
            owner_end,
            owner_first_token,
            owner_end_token,
            first_token,
            end_token,
        });
    }
    files
}

struct Active<'tcx> {
    candidate: Candidate,
    checkpoint: OhmResidentScalarTailSnapshot<'tcx>,
}

struct Outcome {
    mode: &'static str,
    reason: &'static str,
    analysis: u128,
    errors: usize,
    graph_revision: u64,
    positions: Option<(usize, usize, usize, usize)>,
    owner_positions: Option<(usize, usize)>,
    diagnostic_epoch: &'static str,
}

impl Outcome {
    fn fallback(reason: &'static str, errors: usize, graph_revision: u64) -> Self {
        Self {
            mode: "fallback",
            reason,
            analysis: 0,
            errors,
            graph_revision,
            positions: None,
            owner_positions: None,
            diagnostic_epoch: "retained",
        }
    }

    fn noop(errors: usize, graph_revision: u64) -> Self {
        Self {
            mode: "noop",
            reason: "-",
            analysis: 0,
            errors,
            graph_revision,
            positions: None,
            owner_positions: None,
            diagnostic_epoch: "retained",
        }
    }
}

fn check<'tcx>(
    tcx: TyCtxt<'tcx>,
    path: &Path,
    files: &mut BTreeMap<PathBuf, FileState>,
    active: &mut BTreeMap<PathBuf, Active<'tcx>>,
    errors: &mut usize,
    revision: &mut u64,
) -> Outcome {
    let Ok(path) = std::fs::canonicalize(path) else {
        return Outcome::fallback("unreadable-path", *errors, *revision);
    };
    let Some(file) = files.get_mut(&path) else {
        return Outcome::fallback("untracked-source-file", *errors, *revision);
    };
    let Ok(text) = std::fs::read_to_string(&path) else {
        return Outcome::fallback("unreadable-file", *errors, *revision);
    };
    if text == file.accepted {
        return Outcome::noop(*errors, *revision);
    }
    // A fresh parser owns a fresh source map; using rustc's warmed source map under the same
    // filename would return the original contents. Parse the full newly read module, not only
    // the changed token. `mod child;` is deliberately not expanded at this step.
    let session = ParseSess::new();
    if !validate_file(&session, &text) {
        return Outcome::fallback("file-does-not-parse", *errors, *revision);
    }
    let tokens = tokenize(&text);
    let (accepted_prefix, _) = common_tokens(&file.accepted_tokens, &file.accepted, &tokens, &text);
    if accepted_prefix == file.accepted_tokens.len() && accepted_prefix == tokens.len() {
        // Source-location changes can affect macro expansion even with identical non-trivia
        // tokens. Restrict this benchmark's fast path to the active function in source files
        // using only an explicit, small set of source-independent standard macros/attributes.
        let Some(previous) = active.get(&path) else {
            return Outcome::fallback("trivia-outside-active-source-owner", *errors, *revision);
        };
        let candidate = &previous.candidate;
        let owner_end_token =
            candidate.owner_end_token - (candidate.end_token - candidate.first_token) + 1;
        let owner_tokens = &file.accepted_tokens[candidate.owner_first_token..owner_end_token];
        let (start, end) = raw_change(&file.accepted, &text);
        if start
            < owner_tokens
                .first()
                .unwrap()
                .start
                .min(candidate.owner_start)
            || end > owner_tokens.last().unwrap().end
        {
            return Outcome::fallback("trivia-outside-active-source-owner", *errors, *revision);
        }
        if !source_independent_macros(&file.accepted_tokens, &file.accepted, &file.imported_names) {
            return Outcome::fallback("trivia-may-change-macro-expansion", *errors, *revision);
        }
        file.accepted = text;
        file.accepted_tokens = tokens;
        return Outcome::noop(*errors, *revision);
    }
    let (prefix, suffix) = common_tokens(&file.baseline_tokens, &file.baseline, &tokens, &text);
    let baseline_equal = prefix == file.baseline_tokens.len() && prefix == tokens.len();
    let (selected, replacement, new_start, new_end) = if baseline_equal {
        let Some(previous) = active.get(&path) else {
            unreachable!("different accepted token streams imply an active edit");
        };
        let candidate = previous.candidate.clone();
        let new_start = tokens[candidate.first_token].start;
        let new_end = tokens[candidate.end_token - 1].end;
        (candidate, None, new_start, new_end)
    } else {
        let mut matches = file.candidates.iter().filter(|candidate| {
            let before = candidate.first_token;
            let after = file.baseline_tokens.len() - candidate.end_token;
            tokens.len() == before + 1 + after && prefix >= before && suffix >= after
        });
        let Some(candidate) = matches.next().cloned() else {
            return Outcome::fallback("change-is-not-one-complete-source-tail", *errors, *revision);
        };
        if matches.next().is_some() {
            return Outcome::fallback("ambiguous-source-tail", *errors, *revision);
        }
        if let Some(previous) = active.get(&path)
            && previous.candidate.owner != candidate.owner
        {
            return Outcome::fallback("another-semantic-edit-active", *errors, *revision);
        }
        // rustc resolves and lints imports before the resident body query graph. Removing
        // a use in this tail can add an unused-import diagnostic that native reanalysis does
        // not emit. Conservatively send any tail naming something found in a source `use`
        // tree to a fresh compiler; resolving whether an identical spelling belongs to this
        // import would itself require retaining resolver state the prototype does not own.
        if file.baseline_tokens[candidate.first_token..candidate.end_token]
            .iter()
            .copied()
            .filter_map(|token| token_identifier(token, &file.baseline))
            .any(|name| file.imported_names.contains(name))
        {
            return Outcome::fallback("tail-may-change-import-usage", *errors, *revision);
        }
        let token = tokens[candidate.first_token];
        let Some(literal) = scalar(&session, &text[token.start..token.end]) else {
            return Outcome::fallback("replacement-is-not-a-supported-scalar", *errors, *revision);
        };
        (candidate, Some(literal), token.start, token.end)
    };
    let had_previous = active.contains_key(&path);
    let accepted_start = file.accepted_tokens[selected.first_token].start;
    let accepted_end = if had_previous {
        file.accepted_tokens[selected.first_token].end
    } else {
        file.accepted_tokens[selected.end_token - 1].end
    };
    // Token comparison locates a candidate while deliberately ignoring trivia. Do not let a
    // scalar change or restoration piggyback unrelated raw source edits through that check:
    // trivia must arrive separately so the active-owner and whole-file macro guards run. A
    // restoration also reinstates the exact original HIR, so its expression must have exactly
    // the original spelling, including its internal trivia.
    if file.accepted[..accepted_start] != text[..new_start]
        || file.accepted[accepted_end..] != text[new_end..]
    {
        return Outcome::fallback(
            "semantic-edit-also-changes-source-trivia",
            *errors,
            *revision,
        );
    }
    if replacement.is_none()
        && text[new_start..new_end] != file.baseline[selected.start..selected.end]
    {
        return Outcome::fallback(
            "restored-tail-source-differs-from-baseline",
            *errors,
            *revision,
        );
    }
    // A scalar can legitimately shrink a source tail. In a file with unknown macros, however,
    // changing line count shifts every later invocation, and changing width can shift a later
    // invocation on the same line. Permit those changes only when the whole-file macro policy
    // has ruled out source-sensitive expansion. Macro-shaped original tails are always rejected.
    let original_tail_tokens = &file.baseline_tokens[selected.first_token..selected.end_token];
    if original_tail_tokens
        .iter()
        .any(|token| token.kind == TokenKind::Bang)
    {
        return Outcome::fallback(
            "semantic-tail-contains-macro-punctuation",
            *errors,
            *revision,
        );
    }
    let accepted_tail = &file.accepted[accepted_start..accepted_end];
    let next_tail = &text[new_start..new_end];
    let newline_count = |text: &str| text.bytes().filter(|&byte| byte == b'\n').count();
    let suffix_line = file.accepted[accepted_end..].split('\n').next().unwrap();
    let shifts_following_source = newline_count(accepted_tail) != newline_count(next_tail)
        || (accepted_tail.len() != next_tail.len()
            && !suffix_line.chars().all(rustc_lexer::is_whitespace));
    if shifts_following_source
        && !source_independent_macros(&file.accepted_tokens, &file.accepted, &file.imported_names)
    {
        return Outcome::fallback(
            "semantic-tail-may-shift-macro-locations",
            *errors,
            *revision,
        );
    }
    if let Some(previous) = active.remove(&path) {
        let eviction = unsafe {
            tcx.ohm_restore_private_scalar_tail(previous.checkpoint)
                .expect("the driver owns the sole checkpoint and rejects incompatible changes")
        };
        *revision = eviction.revision;
    }
    if let Some(replacement) = replacement {
        match unsafe { tcx.ohm_override_private_scalar_tail(selected.owner, replacement) } {
            Ok((checkpoint, eviction)) => {
                *revision = eviction.revision;
                active.insert(
                    path,
                    Active {
                        candidate: selected.clone(),
                        checkpoint,
                    },
                );
            }
            Err(reason) => {
                // No checkpoint existed here: changing an already accepted tail first restores
                // the same verified owner, for which a validated scalar cannot be rejected.
                // A first unsupported HIR owner is rejected without changing the native graph.
                assert!(
                    !had_previous,
                    "a previously validated owner became uneditable: {reason}"
                );
                assert_eq!(
                    tcx.query_system.resident.as_ref().unwrap().stats().revision,
                    *revision
                );
                return Outcome::fallback(reason, *errors, *revision);
            }
        }
    }
    tcx.dcx().reset_err_count();
    let analysis_started = Instant::now();
    let _ = rustc_driver::catch_fatal_errors(|| tcx.ensure_ok().analysis(()));
    let analysis = analysis_started.elapsed().as_nanos();
    *errors = tcx.dcx().err_count();
    file.accepted = text;
    file.accepted_tokens = tokens;
    Outcome {
        mode: "resident",
        reason: "-",
        analysis,
        errors: *errors,
        graph_revision: *revision,
        positions: Some((selected.start, selected.end, new_start, new_end)),
        owner_positions: Some((selected.owner_start, selected.owner_end)),
        diagnostic_epoch: "request",
    }
}

fn fresh(tcx: TyCtxt<'_>) {
    let started = Instant::now();
    let _ = rustc_driver::catch_fatal_errors(|| tcx.ensure_ok().analysis(()));
    let elapsed = started.elapsed().as_nanos();
    let errors = tcx.dcx().err_count();
    stdout(format_args!(
        "fresh\t{}\t{elapsed}\t{errors}",
        std::process::id()
    ));
    tcx.dcx().reset_err_count();
}

#[derive(Default)]
struct BuildGuard {
    baseline_errors: bool,
    errored_owners: BTreeSet<(PathBuf, usize, usize)>,
    rejected_paths: BTreeSet<PathBuf>,
    sources: BTreeMap<PathBuf, Vec<u8>>,
}

fn source_key(path: &Path) -> PathBuf {
    std::fs::canonicalize(path).unwrap_or_else(|_| {
        if path.is_absolute() {
            path.to_owned()
        } else {
            std::env::current_dir().unwrap().join(path)
        }
    })
}

impl BuildGuard {
    fn new(tcx: TyCtxt<'_>, baseline_errors: bool) -> Self {
        let sources = tcx
            .sess
            .source_map()
            .files()
            .iter()
            .filter(|source| source.src.is_some())
            .filter_map(|source| {
                let path = source.name.clone().into_local_path()?;
                let path = std::fs::canonicalize(path).ok()?;
                let bytes = std::fs::read(&path).ok()?;
                Some((path, bytes))
            })
            .collect();
        Self {
            baseline_errors,
            sources,
            ..Self::default()
        }
    }

    fn checked(&mut self, path: &Path, outcome: &Outcome) {
        let path = source_key(path);
        if outcome.mode == "fallback" {
            self.rejected_paths.insert(path);
        } else {
            self.rejected_paths.remove(&path);
            if let Some((start, end)) = outcome.owner_positions {
                let owner = (path, start, end);
                // Resident reanalysis clears rustc's global diagnostic counter. Keep a
                // conservative per-owner error ledger so a later check in another source file
                // cannot turn an earlier, still-active type error into a buildable crate.
                if outcome.errors == 0 {
                    self.errored_owners.remove(&owner);
                } else {
                    self.errored_owners.insert(owner);
                }
            }
        }
    }

    fn rejection(
        &self,
        tcx: TyCtxt<'_>,
        files: &BTreeMap<PathBuf, FileState>,
    ) -> Option<&'static str> {
        if self.baseline_errors {
            return Some("initial-analysis-had-errors");
        }
        if !self.errored_owners.is_empty() || tcx.dcx().has_errors_or_delayed_bugs().is_some() {
            return Some("accepted-source-has-errors");
        }
        for path in &self.rejected_paths {
            let Some(baseline) = self.sources.get(path) else {
                return Some("source-revision-requires-fresh-compiler");
            };
            if std::fs::read(path).as_deref().ok() != Some(baseline.as_slice()) {
                return Some("source-revision-requires-fresh-compiler");
            }
        }
        // Verify all file-backed input loaded by the initial compiler, including module files
        // without eligible HIR owners and inputs from `include!` or `include_bytes!`. A client
        // cannot publish a binary after saving a known source file without checking it first.
        for (path, original) in &self.sources {
            let accepted = files
                .get(path)
                .map_or(original.as_slice(), |file| file.accepted.as_bytes());
            if std::fs::read(path).as_deref().ok() != Some(accepted) {
                return Some("source-on-disk-does-not-match-accepted-revision");
            }
        }
        None
    }
}

enum ResidentExit {
    Stop,
    Build { version: String, started: Instant },
    Rejected,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum BuildMode {
    Disabled,
    Exit,
    Repeat,
}

fn repeat_build(
    compiler: &interface::Compiler,
    tcx: TyCtxt<'_>,
    version: &str,
    started: Instant,
) -> bool {
    let backend = &*compiler.codegen_backend;
    let mut analysis_reported = false;
    let report_analysis = || {
        marker("build-analysis-end", version);
        stdout(format_args!(
            "build-analysis\t{version}\t{}",
            started.elapsed().as_nanos()
        ));
    };
    let succeeded = rustc_driver::catch_fatal_errors(|| {
        passes::write_dep_info(tcx);
        passes::write_interface(tcx);
        tcx.ensure_ok().analysis(());
        report_analysis();
        analysis_reported = true;
        let linker = Linker::codegen_and_build_linker(tcx, backend);
        tcx.report_unused_features();
        // The ordinary driver links after leaving the compiler context to free it sooner. A
        // resident compiler deliberately retains it; linking itself only consumes this job.
        linker.link(tcx.sess, backend);
    })
    .is_ok();
    if !analysis_reported {
        report_analysis();
    }
    if succeeded {
        for unit in tcx
            .query_system
            .resident
            .as_ref()
            .unwrap()
            .codegen_cache_report()
        {
            stdout(format_args!(
                "build-codegen-unit\t{version}\t{}\t{}\t{}",
                unit.name,
                if unit.reused { "reused" } else { "compiled" },
                unit.fingerprint
            ));
        }
    }
    marker("build-finished", version);
    stdout(format_args!(
        "build-finished\t{version}\t{}\t{}",
        started.elapsed().as_nanos(),
        if succeeded { "ok" } else { "failed" }
    ));
    succeeded
}

fn resident<'tcx>(
    compiler: &interface::Compiler,
    tcx: TyCtxt<'tcx>,
    mode: BuildMode,
) -> ResidentExit {
    assert!(tcx.query_system.resident.is_some());
    if mode == BuildMode::Repeat
        && let Some(cache) = std::env::var_os("OHM_RUFF_CODEGEN_CACHE")
    {
        let cache = PathBuf::from(cache);
        std::fs::create_dir_all(&cache).expect("could not create private codegen cache");
        tcx.query_system
            .resident
            .as_ref()
            .unwrap()
            .configure_codegen_cache(cache)
            .expect("could not configure private codegen cache");
    }
    marker("start", "baseline");
    let started = Instant::now();
    let _ = rustc_driver::catch_fatal_errors(|| tcx.ensure_ok().analysis(()));
    let elapsed = started.elapsed().as_nanos();
    let mut errors = tcx.dcx().err_count();
    marker("end", "baseline");
    let mut files = files(tcx);
    let mut active = BTreeMap::new();
    let mut graph_revision = 0;
    let mut last_version = 0;
    let mut build_guard = (mode != BuildMode::Disabled).then(|| {
        BuildGuard::new(
            tcx,
            errors > 0 || tcx.dcx().has_errors_or_delayed_bugs().is_some(),
        )
    });
    let mut backend_failed = false;
    stdout(format_args!("ready\t{}\t{elapsed}", std::process::id()));
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        if line == "quit" {
            tcx.dcx().reset_err_count();
            stdout(format_args!("bye"));
            return ResidentExit::Stop;
        }
        let mut fields = line.splitn(3, '\t');
        let command = fields.next();
        let version = fields.next().expect("version");
        let sequence: u64 = version.parse().expect("nonnegative integer version");
        if command == Some("build") {
            let started = Instant::now();
            marker("build-start", version);
            let reason = match &build_guard {
                None => Some("build-mode-is-disabled"),
                Some(_) if fields.next().is_some() => Some("unexpected-build-argument"),
                Some(_) if sequence != last_version => Some("source-version-is-not-current"),
                Some(_) if backend_failed => Some("previous-codegen-failed"),
                Some(guard) => guard.rejection(tcx, &files),
            };
            if let Some(reason) = reason {
                if mode == BuildMode::Repeat {
                    marker("build-rejected", version);
                }
                stdout(format_args!("build\t{version}\trejected\t{reason}"));
                if mode == BuildMode::Repeat {
                    continue;
                }
                return ResidentExit::Rejected;
            }
            stdout(format_args!("build\t{version}\tready\t-"));
            if mode == BuildMode::Repeat {
                backend_failed = !repeat_build(compiler, tcx, version, started);
                continue;
            }
            return ResidentExit::Build {
                version: version.to_owned(),
                started,
            };
        }
        assert_eq!(command, Some("check"));
        assert!(sequence > last_version, "source versions must increase");
        last_version = sequence;
        let path = fields.next().expect("source path");
        marker("start", version);
        let started = Instant::now();
        let result = if backend_failed {
            Outcome::fallback("previous-codegen-failed", errors, graph_revision)
        } else {
            check(
                tcx,
                Path::new(path),
                &mut files,
                &mut active,
                &mut errors,
                &mut graph_revision,
            )
        };
        if let Some(guard) = &mut build_guard {
            guard.checked(Path::new(path), &result);
        }
        let elapsed = started.elapsed().as_nanos();
        marker("end", version);
        let positions = result.positions.map_or_else(
            || "-\t-\t-\t-".to_owned(),
            |(old_start, old_end, new_start, new_end)| {
                format!("{old_start}\t{old_end}\t{new_start}\t{new_end}")
            },
        );
        let owner = result.owner_positions.map_or_else(
            || "-\t-".to_owned(),
            |(start, end)| format!("{start}\t{end}"),
        );
        stdout(format_args!(
            "result\t{version}\t{}\t{}\t{elapsed}\t{}\t{}\t{}\t{positions}\t{}\t{owner}",
            result.mode,
            result.reason,
            result.analysis,
            result.errors,
            result.graph_revision,
            result.diagnostic_epoch,
        ));
    }
    panic!("parent closed stdin without sending quit or build");
}

#[derive(Default)]
struct Driver {
    build: Option<(String, Instant)>,
    rejected_build: bool,
}

impl Callbacks for Driver {
    fn config(&mut self, config: &mut interface::Config) {
        // Match the stock rustc binary's TimePassesCallbacks, including diagnostic type names.
        config.opts.trimmed_def_paths = true;
    }

    fn after_expansion<'tcx>(
        &mut self,
        compiler: &interface::Compiler,
        tcx: TyCtxt<'tcx>,
    ) -> Compilation {
        match std::env::var("OHM_RUFF_SOURCE_MODE").as_deref() {
            Ok(mode @ ("resident" | "resident-build" | "resident-repeat-build")) => {
                let mode = match mode {
                    "resident" => BuildMode::Disabled,
                    "resident-build" => BuildMode::Exit,
                    "resident-repeat-build" => BuildMode::Repeat,
                    _ => unreachable!(),
                };
                match resident(compiler, tcx, mode) {
                    ResidentExit::Stop => Compilation::Stop,
                    ResidentExit::Build { version, started } => {
                        self.build = Some((version, started));
                        Compilation::Continue
                    }
                    ResidentExit::Rejected => {
                        self.rejected_build = true;
                        Compilation::Stop
                    }
                }
            }
            Ok("fresh") => {
                fresh(tcx);
                Compilation::Stop
            }
            _ => panic!(
                "OHM_RUFF_SOURCE_MODE must be resident, resident-build, resident-repeat-build, or fresh"
            ),
        }
    }

    fn after_analysis<'tcx>(&mut self, _: &interface::Compiler, _: TyCtxt<'tcx>) -> Compilation {
        if let Some((version, started)) = &self.build {
            marker("build-analysis-end", version);
            stdout(format_args!(
                "build-analysis\t{version}\t{}",
                started.elapsed().as_nanos()
            ));
        }
        Compilation::Continue
    }
}

fn main() -> std::process::ExitCode {
    let args = std::env::args().collect::<Vec<_>>();
    let mut driver = Driver::default();
    let exit =
        rustc_driver::catch_with_exit_code(|| rustc_driver::run_compiler(&args, &mut driver));
    if let Some((version, started)) = &driver.build {
        marker("build-finished", version);
        stdout(format_args!(
            "build-finished\t{version}\t{}",
            started.elapsed().as_nanos()
        ));
    }
    if driver.rejected_build {
        std::process::ExitCode::FAILURE
    } else {
        exit
    }
}
