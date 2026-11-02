"""Three actual independently authenticated stage1 roles with parked directories at one Rustup path."""

from copy import copy
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scope
import worker as legacy

rt = legacy.runtime
need, sha, save = scope.base.need, scope.base.sha, scope.base.save

from arm_names import INTERNAL


class ThreeRuntime(rt.Runtime):
    def __init__(self, work, inputs, out, tools, older):
        self.origins = {"P": (inputs, "P"), "C": (inputs, "C"), "C2": (older, "C")}
        super().__init__(work, inputs, out, tools)
        with scope.product("C2"):
            old = scope.base.capsule.admit(older / "capsule")
        self.old_proof = json.loads((older / "source-qualification.json").read_bytes())
        old_docs = json.loads((older / "docs-qualification.json").read_bytes())
        need(
            self.manifests["P"] == old["P"]
            and self.docs["actual"]["P"]["rustdoc"] == old_docs["actual"]["P"]["rustdoc"]
            and sha(inputs / "doc-products/P/rustdoc")
            == sha(older / "doc-products/P/rustdoc")
            == old_docs["actual"]["P"]["rustdoc"][0],
            "independent entire parent kits or their newly compiled rustdocs differ",
        )
        self.manifests["C2"] = old["C"]
        self.parked["C2"] = older / "parked/defer"
        names = old["C"]
        park = self.parked["C2"]
        (drv,) = [n for n in names if n.startswith("lib/librustc_driver-")]
        chosen = {
            "front": "bin/rustc",
            "cargo": "bin/cargo",
            "wild": rt.support.WILD,
            "driver": drv,
            "llvm": rt.transport.llvm_name(park, names),
        }
        self.refs["C2"] = {
            k: {"name": f, "sha": names[f][0], "id": rt.stat_id(park / f)}
            for k, f in chosen.items()
        }
        need(
            all(
                sha(park / r["name"]) == r["sha"]
                and (park / r["name"]).samefile(older / "capsule/objects" / r["sha"])
                for r in self.refs["C2"].values()
            )
            and self.refs["C2"]["driver"]["sha"] == self.old_proof["physical"]["C"]["driver"],
            "incorrect executing prior physical role",
        )
        self.select("C2")
        versions = {}
        for name in ("rustc", "cargo"):
            actual = Path(
                subprocess.check_output(
                    ["rustup", "which", "--toolchain", "ohm", name], env=self.base, text=True
                ).strip()
            )
            need(actual.samefile(self.sdk / "bin" / name), "different older role rustup binary")
            versions[name] = subprocess.check_output(
                [name, "+ohm", "-vV"], env=self.base, text=True
            )
        # The previous independently made source capsule names this physical arm C.
        # Its native rustdoc and library inodes remain the older kit's own.
        doc = copy(self)
        doc.inputs = older
        doc.docs = old_docs
        doc.refs = {"C": self.refs["C2"]}
        rendered = rt.doc_support.exercise(doc, "C", out / "doc-control-C2")
        manifest = json.loads((out / "physical-roles.json").read_bytes())
        need(
            manifest["versions"]["P"] == manifest["versions"]["C"] == versions
            and len({r["driver"]["sha"] for r in self.refs.values()}) == 3
            and all(
                len({r[n]["sha"] for r in self.refs.values()}) == 1
                for n in ("cargo", "llvm", "wild")
            ),
            "three distinct physical compilers with the same shared tool inputs were not installed",
        )
        manifest["kits"] = self.refs
        manifest["versions"]["C2"] = versions
        manifest["documentation"]["C2"] = rendered
        manifest["C2_source_qualification"] = sha(older / "source-qualification.json")
        manifest["parent_member_count"] = len(old["P"])
        manifest["C2_source_bound_previous_parent"] = self.old_proof["physical"]["P"]
        manifest["aliases"] = INTERNAL
        temporary = out / "initial-two-physical-roles.json"
        (out / "physical-roles.json").rename(temporary)
        manifest["initial_two_roles"] = sha(temporary)
        save(out / "physical-roles.json", manifest)
        self.select("P")

    def select(self, role):
        need(role in self.parked, "unrecognized enrolled physical role")
        if self.active != role:
            if self.active:
                need(
                    not self.parked[self.active].exists(),
                    "active physical compiler directory was replaced",
                )
                self.sdk.rename(self.parked[self.active])
            need(
                not self.sdk.exists()
                and self.parked[role].is_dir()
                and not self.parked[role].is_symlink(),
                "not a parked real compiler directory",
            )
            self.parked[role].rename(self.sdk)
            self.active = role
        origin, label = self.origins[role]
        need(
            (self.sdk / "bin/rustdoc").samefile(origin / "doc-products" / label / "rustdoc"),
            "changed matching documentation inode",
        )
        for name, rec in self.refs[role].items():
            item = self.sdk / rec["name"]
            need(
                rt.stat_id(item) == rec["id"]
                and item.samefile(origin / "capsule/objects" / rec["sha"]),
                "different physical compiler, native linker or shared library",
            )
            setattr(self, name, item)

    def finish(self):
        self.sdk.rename(self.parked[self.active])
        self.active = None
        for role, directory in self.parked.items():
            origin, label = self.origins[role]
            for filename, record in self.manifests[role].items():
                path = directory / filename
                need(
                    path.samefile(origin / "capsule/objects" / record[0])
                    and sha(path) == record[0],
                    "enrolled role changed during study",
                )
            need(
                (directory / "bin/rustdoc").samefile(origin / "doc-products" / label / "rustdoc")
                and sha(directory / "bin/rustdoc")
                == json.loads((origin / "docs-qualification.json").read_bytes())["actual"][label][
                    "rustdoc"
                ][0],
                "source-bound rustdoc changed",
            )
        for which, arm in (("C2", "C2"), ("C3b", "C")):
            with scope.product(which):
                origin = self.origins[arm][0]
                again = scope.base.capsule.admit(origin / "capsule")
                need(
                    again["P"] == self.manifests["P"] and again["C"] == self.manifests[arm],
                    "different completed complete SDK",
                )
