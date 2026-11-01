"""Reopen raw Cargo messages, native tool receipts, executable bodies and rendered documentation."""
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile

COLLISION = "found crates (`ruff_text_size` and `ruff_text_size`) with colliding StableCrateId values"
PAGES = ("index.html", "struct.TextSize.html", "fn.line_start.html")
STATES = ("default-cold-doc", "default-build-doc", "off-cold-doc", "off-build-doc")


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def js(path):
    return json.loads(path.read_bytes())


def raw(path, limit=1 << 20):
    with gzip.open(path, "rb") as f:
        data = f.read(limit + 1)
    need(len(data) <= limit, "oversized captured file")
    return data


class Document(HTMLParser):
    def __init__(self, data):
        super().__init__()
        self.links = []
        self.words = []
        self.feed(data.decode())
        self.close()

    def handle_data(self, text):
        self.words.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links += [v.split("#")[0].rsplit("/", 1)[-1] for k, v in attrs if k == "href" and v]


def pages(folder, claimed):
    need(set(claimed) == set(PAGES), "missing HTML inventory")
    for name in PAGES:
        data = raw(folder / (name + ".gz"), 3 << 20)
        need(sha(data) == claimed[name], "changed HTML body")
        html = Document(data)
        words = " ".join(" ".join(html.words).split())
        if name == "index.html":
            need(set(PAGES[1:]) <= set(html.links), "facade lacks links to documented items")
        elif name == "struct.TextSize.html":
            need("TextSize" in words and "A measure of text length." in words, "original inline type missing")
        else:
            need("line_start" in words and "TextSize" in words and
                 "Returns the start of the line that contains the given byte offset." in words,
                 "nominal crossing documentation missing")


def call(folder, argv, ctx, code):
    need(js(folder / "invocation.json") == dict(argv=argv, **ctx) and js(folder / "exit.json") == code,
         "incorrect process invocation or exit")
    return raw(folder / "stdout.gz"), raw(folder / "stderr.gz")


def cargo(folder, argv, ctx, code):
    stdout, stderr = call(folder, argv, ctx, code)
    all_rows = [json.loads(line) for line in stdout.splitlines()]
    need(all_rows[-1] == {"reason":"build-finished", "success":code == 0}
         and sum(r["reason"] == "build-finished" for r in all_rows) == 1 and
         b"internal compiler error" not in stderr.lower(), "incomplete Cargo verdict")
    errors = [r["message"]["message"] for r in all_rows if r["reason"] == "compiler-message"
              and r["message"]["level"] == "error"]
    result = js(folder / "result.json")
    need(errors == ([COLLISION] if code else []) and errors == result["errors"] and result["status"] == code,
         "wrong rustdoc diagnostic")
    units = [r for r in all_rows if r["reason"] == "compiler-artifact"]
    files = {p:r for r in units for p in r["filenames"] if Path(p).suffix in (".rmeta", ".rlib")}
    need(set(files) == set(result["products"]), "typed products missing")
    for p, r in files.items():
        prod = result["products"][p]
        need(any(Path(p).is_relative_to(ctx["env"][k]) for k in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"))
             and (prod["package"], prod["fresh"]) == (r["package_id"], r["fresh"])
             and prod["bytes"] > 0 and len(prod["sha256"]) == 64, "foreign typed product")
    return units, result


def reopen(root, expected, binding, execute):
    r = js(root / "complete.json")
    role, host = r["role"], r["host"]
    need(role in {"published-22", "corrected", "fd98-control"} and host == expected["host"]
         and js(root / "sources.json") == binding and r["source"] == binding["archive"], "wrong role or source")
    need(set(r["cases"]) == set(STATES) and r["cases"] == js(root / "progress.json"), "missing case")
    original = js(root / "default-cold-doc/doc/invocation.json")
    ctx = {k:original[k] for k in ("env", "cwd")}
    src, env = Path(ctx["cwd"]), ctx["env"]
    dirs = {"HOME":"user", "TMPDIR":"tmp", "RUSTUP_HOME":"rustup", "CARGO_HOME":"registry",
            "CARGO_TARGET_DIR":"target", "CARGO_BUILD_BUILD_DIR":"build"}
    allowed = set(dirs) | {"PATH", "LC_ALL", "CARGO_TERM_COLOR", "CARGO_NET_OFFLINE", "RUSTUP_AUTO_INSTALL"}
    if host == "aarch64-apple-darwin":
        allowed |= {"LLVM_PROFILE_FILE", "SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET"}
    need(src.name == "project" and src.is_absolute() and all(Path(env[k]) == src.parent / v for k,v in dirs.items())
         and env["CARGO_NET_OFFLINE"] == "true" and env["RUSTUP_AUTO_INSTALL"] == "0"
         and set(env) <= allowed, "wrong Cargo roots or environment")
    for tool in ("cargo", "rustc", "rustdoc"):
        ident = r["tools"][tool]
        vv = call(root / "identity" / (tool + "-version"), [tool, "+ohm", "-vV"], ctx, 0)[0].decode()
        which = call(root / "identity" / (tool + "-which"), ["rustup", "which", "--toolchain", "ohm", tool], ctx, 0)[0]
        commit = expected["cargo_commit" if tool == "cargo" else "rust_commit"]
        need(ident["version"] == vv and vv.splitlines()[0].startswith(tool + " ")
             and "commit-hash: " + commit in vv.splitlines() and "host: " + host in vv.splitlines()
             and ident["path"] == which.decode().strip() == str(Path(env["RUSTUP_HOME"]) / "toolchains/ohm/bin" / tool)
             and ident["sha256"] == expected[tool], "different native " + tool)
    summary = {}
    for state in STATES:
        case = root / state
        default, trained = state.startswith("default-"), "build-doc" in state
        prefix = ["cargo", "+ohm"] + ([] if default else ["-Zohm-defaults=no"])
        common = ["--offline", "--locked", "-j2", "--message-format=json"]
        code = 101 if role != "corrected" and default else 0
        phase = r["cases"][state]
        need(set(phase) == ({"build", "doc"} if trained else {"doc"}), "wrong phase inventory")
        units, doc = cargo(case / "doc", prefix + ["doc", "-p", "facade", "--no-deps"] + common, ctx, code)
        leaves = [u for u in units if u["target"]["name"] == "ruff_text_size"]
        kinds = sorted(sorted(Path(p).suffix for p in u["filenames"]) for u in leaves)
        need(kinds == ([[".rlib", ".rmeta"], [".rmeta"]] if code else [[".rmeta"]])
             and {u["target"]["name"] for u in units} == {"memchr", "ruff_text_size", "ruff_source_file"} | (set() if code else {"facade"})
             and doc == phase["doc"], "wrong leaf shapes or nominal producer")
        if code:
            need("pages" not in doc and not any((case / "doc" / (n + ".gz")).exists() for n in PAGES),
                 "false documentation success")
        else:
            pages(case / "doc", doc["pages"])
        result = {"doc_exit":code, "leaf_outputs":kinds, "html":doc.get("pages", {})}
        if trained:
            us, build = cargo(case / "build", prefix + ["build", "-p", "client"] + common, ctx, 0)
            need(build == phase["build"] and {u["target"]["name"] for u in us} ==
                 {"client", "facade", "ruff_text_size", "ruff_source_file", "memchr"}, "wrong built program")
            clients = [u["executable"] for u in us if u["target"]["name"] == "client" and u["executable"]]
            need(len(clients) == 1 and call(case / "native", clients, ctx, 0) == (b"4 5\n", b"")
                 and build["output"] == "4 5\n", "wrong actual nominal crossing")
            body = raw(case / "client.gz", 16 << 20)
            magic = bytes.fromhex("7f454c46" if host.startswith("x86_64") else "cffaedfe")
            need(body.startswith(magic) and sha(body) == build["client"], "different client binary")
            if execute:
                with tempfile.TemporaryDirectory() as td:
                    exe = Path(td) / "client"
                    exe.write_bytes(body)
                    exe.chmod(0o500)
                    proc = subprocess.run([exe], capture_output=True, timeout=15)
                    need((proc.returncode, proc.stdout, proc.stderr) == (0, b"4 5\n", b""), "retained client differs")
            result["client"] = sha(body)
        summary[state] = result
    return {"role":role, "host":host, "tools":expected, "source_path":str(src), "states":summary,
            "clients_executed":bool(execute)}
