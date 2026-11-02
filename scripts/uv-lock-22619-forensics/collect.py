"""Forensic-only carrier. Raw state is snapshotted before any cross-mode equality checks."""
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import content
import report

sys.path.insert(0, str(HERE.parent / "uv-lock-22619"))
import study as base

CFG = json.loads((HERE / "forensics.json").read_bytes())
require = content.require
save = content.save
read = base.read
P, A, B = base.P, base.A, base.B
FILES = {"collect.py", "content.py", "report.py", "prior.json", "forensics.json", "SHA256SUMS"}


def admit():
    require(__debug__ and base.sha(HERE / "prior.json") == CFG["prior_json_sha256"] and
            base.sha(base.H / "study.py") == CFG["old_study_sha256"], "forensic inputs changed")
    # Change only the coordinator branch and workflow identity. All Rust, Cargo, SDK,
    # registry, historical uv, wrapper, source and fixture pins remain the prior contract.
    base.P = base.sdk.CFG = P | {"branch": CFG["branch"], "workflow_sha256": CFG["workflow_sha256"]}
    base.admission()
    w, out, _ = base.roots()
    one = lambda *args: base.git(w, *args).decode().strip()
    require(one("rev-parse", "HEAD^") == CFG["parent"] and
            one("rev-parse", "HEAD:scripts/uv-lock-22619") == CFG["original_scripts_tree"], "changed parent or inherited study")
    prefix = "scripts/uv-lock-22619-forensics/"
    actual = set(one("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "HEAD^", "HEAD").splitlines())
    require(actual == {".github/workflows/ci.yml"} | {prefix + name for name in FILES}, ("unregistered changes", actual))
    listed = set()
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        require(name not in listed and name in FILES and digest == base.sha(HERE / name), "forensic package manifest")
        listed.add(name)
    require(listed == FILES - {"SHA256SUMS"}, "forensic package incomplete")
    save(out / "forensic-authority.json", {"parent": CFG["parent"], "inherited_tree": CFG["original_scripts_tree"],
         "files": {name: base.sha(HERE / name) for name in sorted(FILES)}, "performance_eligible": False})


def prepare():
    base.sdk.configure()
    w, out, work = base.roots()
    out.mkdir(exist_ok=True)
    work.mkdir()
    base.storage(work, P["required_free_gib"] << 30)
    earlier = base.earlier()
    earlier.verified_checkouts(w)
    save(out / "host.json", earlier.cpu_receipt(out))


class Capture:
    def __init__(self, s):
        self.s = s
        self.prior = read(HERE / "prior.json")
        self.base_profile = P["profile"]
        self.paths = set(self.prior["cold_typed_A"])
        require(len(self.paths) == 51 and self.paths == set(self.prior["cold_plain_A"]), "wrong authenticated workspace set")
        self.store = content.Store(s.out, CFG["storage_limit"])
        self.material = {}
        self.forms = {}
        self.status = {}
        self.progress = {}

    def attempt(self, label, operation, run):
        row = self.status.setdefault(label, {})
        require(operation not in row, ("duplicate evidence", label, operation))
        try:
            value = run()
            row[operation] = {"pass": True}
            return value
        except (ValueError, AssertionError, OSError, RuntimeError, subprocess.SubprocessError, KeyError, IndexError, TypeError) as error:
            row[operation] = {"pass": False, "type": type(error).__name__, "error": str(error)[:2400]}
            return None
        finally:
            save(self.s.out / "capture-status.json", self.status)

    def snapshot(self, label, observed=None):
        s = self.s
        data = content.material(s.target, self.paths, observed or {}, self.store, CFG["raw_rmeta_size_limit"])
        self.material[label] = data
        save(s.out / label / "workspace-material.json", data)
        # Verify completeness after saving all attainable objects, including partial snapshots.
        require(not data["errors"] and data["frozen_paths_equal"] and bool(data["sidecars"]), ("incomplete raw inventory", data["errors"][:6]))
        if observed is not None:
            require(data["typed_declared_paths_equal"] and data["typed_declared_bytes_equal"], "typed declaration versus same live bytes")

    def keyed_profile(self, label, form):
        s = self.s
        where = s.out / label
        files = list(s.keys.iterdir())
        # Move the actual raw files out of the stable profile path. A parser/binding
        # failure can still be diagnosed, and never contaminates the next capture.
        loose = s.work / ("raw-profile-" + label)
        loose.mkdir()
        for p in files:
            p.rename(loose / p.name)
        valid = [p for p in loose.iterdir() if p.is_file() and not p.is_symlink() and re.fullmatch(r"uv_lock-[0-9]+\.mm_profdata", p.name)]
        save(where / "profile-directory.json", {"expected": sorted(p.name for p in valid),
                                                "all": sorted(p.name for p in loose.iterdir())})
        for p in sorted(valid):
            canonical = "uv-lock.mm_profdata.gz" if len(files) == 1 else p.name + ".gz"
            packed = base.packed(p, where / canonical, loose)
            save(where / (p.name + ".archive.json"), packed)
        require(len(valid) == len(files) == 1, "missing or additional selected profile files")
        original, = valid
        match = re.fullmatch(r"uv_lock-([0-9]+)\.mm_profdata", original.name)
        require(form is not None and match and int(match[1]) == form["pid"], "selected profile/actual PID binding")
        receipt = read(where / (original.name + ".archive.json"))
        save(where / "profile.json", receipt | {"pid": form["pid"]})

    def visit(self, label, rev, kind, probe=None):
        s = self.s
        base.check_source(s.src, rev)
        where = s.out / label
        where.mkdir()
        keyed = kind == "keyed"
        typed = kind != "plain"
        mode = "typed" if typed else "plain"
        env = s.env
        require("RUSTC_WRAPPER" not in env, "unexpected ordinary wrapper")
        flags = ["-Zself-profile=" + str(s.keys), "-Zself-profile-events=" + P["profile"]]
        if keyed:
            # A rejected prior capture never silently contributes residual files.
            require(not list(s.keys.iterdir()), "stale selected profile directory")
            execdir = where / "executions"
            execdir.mkdir()
            wrapper = base.H / "profile-wrapper.py"
            require(os.access(wrapper, os.X_OK), "registered wrapper not executable")
            env = env | {"RUSTC_WRAPPER": str(wrapper), "OHM_EXPECTED_RUSTC": str(s.rustc), "OHM_PROFILE_DIR": str(s.keys),
                         "OHM_PROFILE_EVENTS": P["profile"], "OHM_PROFILE_ARGV": str(execdir)}
        args = [s.cargo, *P["command"]]
        if typed:
            args += ["-vv", "--message-format=json"]
        compile_result = self.attempt(label, "positive_compile", lambda: s.command(label, mode, args, env))
        if compile_result is None:
            # Recover what the failed compiler actually emitted, without treating it as complete.
            self.attempt(label, "partial_material", lambda: self.snapshot(label))
            if keyed:
                self.attempt(label, "partial_profile", lambda: self.keyed_profile(label, None))
            return False
        stdout, stderr = compile_result
        form = None
        if typed:
            form = self.attempt(label, "typed_declarations_and_argv", lambda: base.observe(stdout, stderr, s.rustc, s.target, s.members))
            if form:
                self.forms[label] = form
                save(where / "typed.json", form)
        self.attempt(label, "material", lambda: self.snapshot(label, form["workspace_rmeta"] if form else None))
        if typed and form:
            def roster():
                events = base.cargo_messages(stdout)
                dirty = collections.Counter(e["target"]["name"].replace("-", "_") for e in events
                                            if e["reason"] == "compiler-artifact" and not e["fresh"])
                processes = collections.Counter(v[v.index("--crate-name") + 1] for v in form["rustcs"])
                require(dirty == processes, ("actual compiler and dirty Cargo-unit crate names", dirty - processes, processes - dirty))
                save(where / "actual-rustc-roster.json", {"processes": sum(processes.values()), "names": dict(sorted(processes.items())),
                                                         "full_argv_sha256": content.digest(base.canonical(sorted(form["rustcs"])))})
            self.attempt(label, "every_dirty_rustc", roster)
            if keyed:
                def execution():
                    receipt, = execdir.glob("*.json")
                    row = base.execution(receipt, form["argv"], flags)
                    form.update(pid=row["pid"], executed_argv=row["executed"])
                    save(where / "typed.json", form)
                self.attempt(label, "selected_executed_argv", execution)
        self.progress[label] = base.progress(stderr)
        save(where / (mode + "-progress.json"), self.progress[label])
        def progress():
            require((typed or stdout == b"") and "uv-lock" in self.progress[label] and "uv-distribution-types" in self.progress[label],
                    "ordinary output or selected dirty progress")
        self.attempt(label, "native_progress", progress)
        # Plain Cargo deliberately emits no child argv. Bind the graph via the
        # separately observed same-phase typed target and a newly decoded live rmeta.
        target = form if typed else self.forms.get(probe)
        if keyed or kind == "plain":
            def graph():
                require(target is not None, "no actual companion compiler vector")
                base.graph(s.target, target["argv"], where)
                obj = read(where / "graph.json")
                require(self.material[label]["rmeta"][obj["rmeta"]]["sha256"] == obj["rmeta_sha256"], "graph/live consumer mismatch")
                save(where / "graph-argv-origin.json", {"cohort": label if typed else probe, "actual_in_this_cargo_invocation": typed,
                                                       "argv_sha256": content.digest(base.canonical(target["argv"]))})
            self.attempt(label, "graph", graph)
        if (keyed or kind == "plain") and not self.status[label]["graph"]["pass"]:
            def retain_unbound_graph():
                # Keep physical material for off-line inspection after a failed
                # exact-vector check. This never satisfies the strict graph gate.
                companion = where / "unbound-graph"
                companion.mkdir()
                fallback = None
                if typed:
                    try:
                        fallback = base.parse_argv(stderr, s.rustc)[0]
                    except (ValueError, KeyError, IndexError):
                        pass
                origin = "actual child parsed from stderr" if fallback else "bounded physical stable-rmeta path"
                if fallback is None:
                    fallback = [str(s.rustc), "-C", "incremental=" + str(s.target / "debug/incremental"),
                                "--out-dir", str((s.target / s.consumer_member).parent)]
                base.graph(s.target, fallback, companion)
                save(companion / "origin.json", {"origin": origin, "strict_graph_admitted": False})
            self.attempt(label, "supplemental_unbound_graph_only", retain_unbound_graph)
        if keyed:
            self.attempt(label, "profile", lambda: self.keyed_profile(label, form))
        # Before any witness process can touch a scratch path, the selected graph,
        # all native bytes and the complete typed process roster have been captured.
        def witness():
            require(target is not None, "missing actual selected-consumer argument vector")
            base.witness.run("A" if rev == A else "B", s.rustc, target["argv"], s.src, where / "witness", s.env)
        self.attempt(label, "native_metadata_witness", witness)
        base.check_source(s.src, rev)
        return True

    def fresh(self, rev):
        self.s.clean(self.s.target)
        self.s.phase(rev)
        require(not self.s.target.exists(), "cold target must start absent")

    def run(self):
        s = self.s
        s.consumer_member, = [name for name in self.paths if Path(name).name.startswith("libuv_lock-")]
        self.fresh(A)
        self.visit("typed-A", A, "typed")
        self.attempt("typed-A", "upstream_behavior", lambda: s.behavior(A, "typed-A", True))
        self.fresh(A)
        parent_built = self.visit("ordinary-A", A, "plain", "typed-A")
        def checkpoint():
            require(parent_built, "failed plain parent cannot seed a first edit")
            s.seal = base.fileset(s.target)
            save(s.out / "parent-snapshot.json", s.seal)
            base.storage(s.work, 3 * s.seal["bytes"] + (8 << 30))
            s.target.rename(s.checkpoint)
            return True
        parent_saved = self.attempt("ordinary-A", "checkpoint", checkpoint)
        self.fresh(A)
        self.visit("ordinary-A-independent", A, "plain", "typed-A")
        def restore():
            require(parent_saved is True, "no authenticated successful plain-A checkpoint")
            s.restore()
            return True
        if self.attempt("typed-warm-B", "restore", restore):
            self.visit("typed-warm-B", B, "typed")
        self.attempt("typed-warm-B", "upstream_behavior", lambda: self.behavior(B, "typed-warm-B", False))
        self.fresh(B)
        self.visit("typed-cold-B", B, "typed")
        self.attempt("typed-cold-B", "upstream_behavior", lambda: s.behavior(B, "typed-cold-B", True))
        self.fresh(B)
        self.visit("ordinary-cold-B", B, "plain", "typed-cold-B")
        if self.attempt("ordinary-warm-B", "restore", restore):
            self.visit("ordinary-warm-B", B, "plain", "typed-warm-B")
        def verify_parent():
            require(parent_saved and base.fileset(s.checkpoint) == s.seal, "original plain-A checkpoint changed")
        self.attempt("ordinary-A", "unchanged_checkpoint", verify_parent)
        self.fresh(A)
        keyed_parent = self.visit("keyed-A", A, "keyed")
        if keyed_parent:
            save(s.out / "keyed-parent-snapshot.json", base.fileset(s.target))
            s.phase(B)
            # No other command visits this target between the genuine keyed A and its first B.
            self.visit("keyed-warm-B", B, "keyed")
        self.fresh(B)
        self.visit("keyed-cold-B", B, "keyed")

    def behavior(self, rev, label, fresh):
        if self.s.changed.read_bytes() != (self.s.old if rev == A else self.s.new):
            self.s.phase(rev)
        self.s.behavior(rev, label, fresh)


def run():
    s = base.Study()
    capture = Capture(s)
    try:
        capture.run()
    finally:
        # An unavailable compiler record never turns a metadata mismatch into a
        # pass. Keep independently attained captures usable after a later refusal.
        result = report.reduce(capture, s.out)
        save(s.out / "forensic-result.json", result)
    require(result["required_evidence_captured"] and result["scoped_compilations_and_witnesses_pass"],
            "incomplete diagnostic acquisition; the retained reports identify each missing operation")


if __name__ == "__main__":
    require(__debug__ and len(sys.argv) == 2 and sys.argv[1] in ("prepare", "intake", "run"), "usage")
    admit()
    {"prepare": prepare, "intake": base.intake, "run": run}[sys.argv[1]]()
