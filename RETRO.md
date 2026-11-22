# Retro — school-prep-agent (2026-11-14 → 2026-11-22)

**Status:** Abandoned (owner decision, 2026-11-22). Conversion will be re-done as a thin
OpenCode harness over the existing `docling-serve` service.
**Read time:** ~5 min. All claims below cite files, reports, or tickets in this repo.

---

## TL;DR

The requirement was *"convert the book's PDF chapters to Markdown via docling-serve; RAG-ingest
for later."* The repo spent 8 days building a **gate-driven, KB-generating, RAG-ingesting
platform** around that requirement, and the only output produced was **1 of 13 chapters**
(`books/chemistry/ICSE-10thGrade/chapter-1.md`) — and even that only after a pilot report was
filed for human sign-off (still pending). The engineering was not bad; the **scope was ~10× the
requirement and the process was heavier than the product**, so effort never arrived as output.

---

## 1. What was asked

`Requirements.md` (17 lines), 2026-11-14:

1. Convert `books/**/chap-*.pdf` → Markdown using the running `docling-serve` (`localhost:5001`).
2. Optional VLM descriptions of images (local Ollama).
3. Use the Markdowns as a RAG knowledge base.
4. **"to start with this can be a locally executable OpenCode based harness. Any additional
   simplified design can be explored."**
5. Step-2 (agentic student/instructor workflows) explicitly deferred.

The last two lines are the key: **simplicity was an explicit preference, and step-2 was out of scope.**

## 2. What was built instead

`DESIGN.md` (199 lines, 11 locked decisions, 4 ADRs → 5) expanded scope to, in addition to
conversion: `chapters.md` index, LLM-drafted `summary.md` with a **human gate**,
`knowledge.yaml` generated *from* the summary with a JSON-schema validator, quarantine, stable
cross-book IDs "merge-ready for a step-3 union", FTS5 + vector hybrid retrieval with RRF fusion,
per-chapter eval query packs with a 4-level provenance chain, and a fifth `verify` stage.
That is **six deliverables where the requirement named one** (the rest were step-2's problem).

Board state at abandonment (`bd list --all`): **38 issues — 12 closed, 24 open, 1 in-progress.**

## 3. The actual output inventory (the "I haven't seen any output" problem)

| Output | State |
|---|---|
| `chapter-1.md` | ✅ The only converted chapter (99 s, standard pipeline, `reports/convert-20261122T004716Z.jsonl`) |
| `chapter-2..13.md` | ❌ 12 open beads tickets for 13 files a batch script already produces |
| `chapters.md`, `summary.md`, `knowledge.yaml` | ❌ None implemented (`plq`, `bso`, `4nl`, `t6u` all open) |
| RAG store `data/library.sqlite` | ❌ `data/` is empty |
| Eval sweep | ❌ `nnw` open |
| Pilot close-out | ❌ `nv8` in-progress — **waiting on human sign-off since 2026-11-22**, though the recommendation was "proceed to chapters 2–13" |
| Uncommitted work + 10 untracked PDFs | `git status`: `chapter-1.md`, `scripts/`, `prompts/`, `evals/`, chapters 4–13 PDFs all untracked |

Note the inversion: every **closed** ticket (`ws8, s3c, 1qm, j99, 5x7, agp, 529, u1k, jo0, y00, 9vg, chw`)
is *infrastructure* — client, normalizer, gate engine, front-matter, orchestrator, batch script.
**All product-shaped tickets are open.** The factory was finished; the factory had made one part.

## 4. What went wrong — six causes

### 1. Scope snowball against an explicit simplicity requirement
One line in the requirements ("the design for building the knowledge graph needs to be fully
completed") was read as *must be built and wired into step-1 acceptance* (DESIGN §9 requires
summary + KB + RAG + eval sweep before step-1 is "done"). In reality the knowledge base serves
step-2 apps that **have not been designed** — so its schema, entity set, and eval pack were all
speculative. Much of step-1 was insurance for a product that doesn't exist yet.

### 2. Process was built before product
BeaDS board + 38 issues (12 of them per-chapter), ADR 5, three human gates, `reports/` JSONL
schema, `.status` contract, detached-batch script, doctor preflight, session-hygiene rules in
`AGENTS.md`, a "joint service track" policy (x6h, "track, never gates"). Each piece is defensible
alone; **stacked, they consumed the entire time budget** — 8 of the 12 closed tickets are
mechanism, not output.

### 3. Strict QA gates were enforcing a contract the platform had already broken
- **Captions:** Gate A required a caption line after every image ref. `docling-serve 1.26`
  *silently dropped* captions — `picture_description_api` deprecated, the replacement SSRF-gated
  off, no `prompt` field anywhere (proven in `ezq`, kept on the board as *deferred*). The gate
  **failed every image chapter** until ADR-0005 decided pictures weren't wanted at all. The gate
  demanded a feature the service no longer offered; the fix was "remove the feature requirement,"
  not "make the service work."
- **Syllabus band (2–15 items):** failed once on a genuinely damaged head-list, and the answer was
  a new LLM clean-pass subsystem (`u1k`) whose *only* customer was that gate. The gates were
  manufacturing tickets, not measuring quality.

### 4. Two service-side bugs became project blockers with no resolution path
- `0kh` (open): VlmPipeline returns **404 "Task result not found"** 2 s after init — the D1 "vlm
  escape hatch for formula-dense chapters" is unusable.
- `ezq` (deferred): picture descriptions dropped (above).

Policy (Q13 / x6h): *"fix in the docling-serve project first, then re-pin here"* — a cross-repo
dependency with **no enforcement and no owner deadline** ("the tracker is a track, never a gate").
Both bugs sat unresolved while local work accumulated against them.

### 5. Single-GPU + interactive-session mismatch
`AGENTS.md` correctly forbids running conversions inside a session (they starve the model
answering you). So conversions had to be detached, checked later, in fresh sessions. Consequence:
**"output" was always in a future turn**, and every handoff dropped context. Evidence of the cost:
`chapter-1.md` — the repo's one output — has
`title: Downloaded from https:// www.studiestoday.com` (an OCR watermark, recurring 20× in the
body). The pilot report flagged it for a human decision on 11-22 ("either accept-and-correct per
chapter, or file a normalizer rule… **Needs your call.**")… and a normalizer rule is a 3-line fix
that a `continue` would have made. Decisions didn't arrive, so quality stayed stuck.

### 6. The "done" bar made 13 usable chapters an invisible deliverable
DESIGN §9 lists book acceptance = chapters + summary (Gate B) + KB (Gate C) + RAG ingest +
eval sweep + report. **"Convert all 13 chapters and look at them" was not a deliverable** — it was
a prerequisite to one. The visible-value path was not in the design; only the finished system was
rewarded. So on any given day the state read as "nothing yet," when the true state was "1 of 13
chapters + a working conversion engine."

## 5. What actually worked (salvage list)

Don't burn the whole repo. This is genuinely reusable:

| Asset | Why it's worth keeping |
|---|---|
| `pipeline/docling_client.py` | Proven contract: frozen form params, 2700 s budget, transient-only retries with backoff. This is ~90% of the "simple harness" idea already tested. |
| `scripts/convert_batch.sh` | Detached, single-instance, doctor preflight — the right answer to the single-GPU problem, independent of the gates. |
| `pipeline/doctor.py` | Cheap service liveness/shape check before wasting GPU hours. |
| `pipeline/normalize.py` (parts) | `<!-- image -->` residue stripping, heading fixes, U+FFFD removal; only needs one added rule: drop `## Downloaded from …` watermark headings. |
| `reports/` format + pilot report | Cheap to keep, useful to copy when debugging the next book. |
| DESIGN.md §7 D9 | A fine *spec* for RAG if you ever want it; treat as a design doc, not a to-do. |
| `sample-code/converter.py` | The original simple one-call approach — the actual shape of the problem. |

Discard as process: per-chapter beads tickets, Gate A/B/C, `knowledge.yaml`/`summary.md`/eval-pack
machinery, the x6h track, most of `AGENTS.md`.

## 6. The simple version (your new idea, concretely)

~One afternoon, same GPU, no new services:

```
OpenCode skill/command "convert-book"
  → for each books/*/chap-N.pdf (skip existing chapter-N.md unless --force):
       POST docling-serve /v1/convert/file   (to_format=markdown, force_ocr=true)
       → strip watermarks + <!-- --> residue + fix heading levels
       → write chapter-N.md (optional 5-line front matter: source, sha256, converted_at)
  → print: N converted, M failed (with the failure printed, not quarantined)
```

- **Output the same day:** 13 Markdown files you can read.
- **No gates**, no KB, no RAG, one command. If a chapter looks wrong, re-run it with
  `--pipeline vlm` (fix `0kh` in `docling-serve` first) or adjust the cleanup rule.
- RAG later, **if and when the step-2 workflows exist** to need it — then DESIGN §7 D9 is the spec.
- The two service bugs (`0kh`, `ezq`) belong to the `docling-serve` project's own tracker,
  with an owner and a date — not to a "jointly managed" track in a retired repo.

## 7. Before you delete anything

- [ ] Commit or consciously drop the working tree (`chapter-1.md`, `scripts/`, `prompts/`, `evals/`, 10 untracked PDFs).
- [ ] The 13 PDFs are your real inputs — they're fine as-is in the folder.
- [ ] File `0kh` (VlmPipeline 404) in the `docling-serve` repo with the log excerpt from
      `logs/batch/convert-batch-20261122T024535Z.log` — it will bite the next project that uses the
      vlm path too.
- [ ] Keep DESIGN.md/ADR 0005 in some notes folder: the "OCR-first, pictures deferred" decision and
      the D9 retrieval spec are the two genuinely reusable design artifacts.

---

## One-line takeaway

> We engineered the *system* of producing chapters (gates, tracks, boards, platforms) before we
> engineered the *path* to chapters — and when the path was finally ready, a human sign-off and two
> service bugs were sitting on it. The requirement asked for Markdown files; the next harness should
> be measured by how soon `ls books/*/chapter-*.md` stops changing — not by how many tickets close.
