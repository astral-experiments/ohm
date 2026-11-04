# Ruff Unicode normalization dependency update

This private QA branch measures a source-built compiler treatment on the real Ruff #21229
upgrade from unicode-normalization 0.1.24 to 0.1.25. C5 is the immediate product parent,
C7 its experimental child. Both source factories call their artifact “candidate”.
Their separate commits, Git trees, immutable archives, and actual rustc driver hashes are
bound in registration.json. Both carry the same released Linux Cargo and Wild and use the
same stage1 bootstrap and normal developer profile. The compiler pair and two pilot
observations are separate from any release or prior benchmark.

The primary counts user instructions retired by the one actual unicode_normalization
rustc and its threads during the edited Ruff check. A kernel exec-stop counter binds that
process to the physical SDK and original source/argv. An independent, untraced complete
Cargo invocation on the same old-to-edited history counts its whole process tree. Both
counters are calibrated on this boot with a forked workload. The build, observer, input
audit, diagnostic, and fresh-control commands are separate from the primary.

Each arm receives empty initial build and target directories, the same visible paths, and
only the two-lock registry inputs. The reader checks 96 typed products, four dirty owners
on the edit, and zero on its first settled command. Each actual extracted source file is
verified against its registered original archive. A private tuple overflow appended to
the checked-out Ruff parser must report the same five-byte source range twice. Its repair
must recover the clean native result. The historical native observer consumes both real
libraries, tests six parser expressions, and checks every valid Unicode scalar. The sole
added result is U+A7F1. Complete old and edited observer images must differ, and every
ordinary edited, settled, repaired and independently empty new observer must match within
that compiler. Both observed registry library formats must match their respective empty
controls. Prior C5 and C7 individually produced differing private Ruff parser metadata
between warm and empty builds; the raw parser bodies are retained separately.

The two pilots each require at least 20% fewer owner instructions and strictly fewer whole
edited-check instructions. Only then may six independent hosts be measured. Every
confirmation must improve both endpoints, and the median of six owner savings must reach
20%. The common cold/settled regression guard, phase roster and blocked assignment are
frozen in registration.json. Six positive outcomes have two-sided exact sign p=0.03125;
the two pilot observations are excluded. All actual paired and absolute values remain
available, including rejected outcomes. This measures instructions, not elapsed time.

From the authorized packaging QA checkout, dispatch the reviewed branch head, then reopen
the official results on Linux x86_64. The reader also executes every distinct retained
observer and compares its complete stdout to the original native observation.

~~~sh
repo=astral-experiments/ohm
branch=charlie/qa-rc24-normalization-price-20261104
head=$(git rev-parse HEAD)
gh-auto workflow run ci.yml -R "$repo" --ref "$branch" -f reviewed_head="$head" -f cohort=pilot
python3 -IB scripts/ruff-normalization-price/review.py pilot /tmp/ohm-norm-pilot --download "$run_id" --head "$head" --out /tmp/ohm-norm-pilot/qualified.json
~~~
