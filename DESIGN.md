# DESIGN — Chapter Conversion & Application-Neutral Knowledge Base

**Status:** Design for sign-off (step 1). Nothing in this document is implemented yet.
**Repo:** `school-prep-agent` (this repo) · **Date:** 2026-11-14
**Input:** `Requirements.md` · **Vocabulary:** `GLOSSARY.md` · **Decisions:** `docs/adr/0001–0004` · **Reference POC:** `~/sandbox/school-prep-harness` (civics/history + approved `rag-spec.md`)

---

## 1. Scope

**In scope (step 1):**
1. A docker-composed **conversion pipeline**: PDF chapter → clean Markdown + VLM figure descriptions, via the running docling-serve.
2. A **Chapter Index** (`chapters.md`) mapping Chapters ↔ Syllabus — the agent's entry point for routing a topic to a Chapter.
3. A fully designed, per-Book **application-neutral knowledge base** (`summary.md` + `knowledge.yaml`) built from the chapters.
4. **RAG ingest** into a local, service-free retrieval store (`data/library.sqlite`: FTS5 + vectors) with a multi-book `registry.yaml` — so step-2 agentic workflows can query immediately.

**Out of scope (step 2, explicitly deferred):**
- Student- and instructor-specific agentic workflows (the stated "2nd step").
- **All consumer-shaped content**: the `skills:` contract, exam `harness` blocks, question-pattern mining, gold-set eval harness (Q21/Q22 deferral; ADR-0004).
- Cross-book "grade-ladder" graph merging (IDs are merge-ready per ADR-0003; the merge pass is later work).
- Non-chemistry books are supported by design (registry-driven) but only the chemistry book is in scope now.

## 2. Environment (verified facts)

| Item | Value |
|---|---|
| Host | DGX-Spark, single-machine, all local |
| Conversion | docling-serve **1.26.0** at `http://localhost:5001` (compose project `docling-serve`, network `docling-serve_default`; see `~/sandbox/docling-serve/docker-compose.yaml`) |
| Figure VLM | Ollama `qwen3-vl:8b` at `http://host.docker.internal:11434` (`granite3.2-vision:latest` fallback) |
| Extraction LLM | Ollama `qwen3.8:27b` |
| Embedder | Ollama `qwen3-embedding` (4096-dim, verified) |
| Runtime | Python 3.12, stdlib + PyYAML (+ `httpx` inside the converter container); **numpy not required** at this scale |
| Constraints | **Zero new long-running services** beyond the composition below; no external SaaS |

## 3. Locked decisions (traceable)

| # | Decision | Source |
|---|---|---|
| D1 | Convert through docling-serve HTTP (`/v1/convert/file`), standard pipeline + `force_ocr` + `do_table_structure` + `include_images` + picture-description (Ollama), per-chapter overridable options incl. `--pipeline vlm` escape hatch | Req. + ADR-0001 |
| D2 | Chapter files keep **structure**: heading hierarchy, markdown tables, LaTeX math where docling emits it, images as files with VLM captions | Q3 gate |
| D3 | `chapters.md` is generated from **chap-00** (contents); **no `chapter-0.md`**; per-chapter Syllabus lives in chapter front matter | Q14 + POC |
| D4 | Per-chapter **idempotency** by PDF `sha256` in front matter + `--force`; per-chapter failure isolation + transient-only retries + `reports/` + non-zero exit | Q4 |
| D5 | No duplication of docling-serve: compose here adds a `converter` service only, on the existing network | Q5 |
| D6 | **Deterministic Python core; agent is operator** (LLM only for figure description + KB extraction) | ADR-0002 |
| D7 | Per-Book KB artifacts with stable, cross-mergeable IDs | ADR-0003 |
| D8 | KB is **application-neutral**: no `skills:`, no exam `harness` block, no eval harness in step 1 | ADR-0004 |
| D9 | Retrieval = FTS5 (BM25) + local vectors (cosine), RRF-fused, single `data/library.sqlite`, mandatory `book_id` filter, structural chunks, `chunk_id = sha1(book_id \|chapter\|section\|text)` | POC `rag-spec.md` (adopted) |
| D10 | Figure-description model = `qwen3-vl:8b` (env-switchable) | Q10 |
| D11 | `Section` = **board-syllabus unit** (CISCE 2025 wording) grouping chapters — not an in-chapter heading | Q19 + POC |

## 4. Book artifact contract

One folder per Book (existing tree is the Book dir):

```
books/chemistry/ICSE-10thGrade/        # Book dir  (book_id: chemistry-icse10-selina)
├── Selina-Concise-Chemistry-10-chap-00.pdf … -chap-N.pdf     # sources (untouched)
├── chapters.md                       # Chapter Index (from chap-00 + front matter)
├── chapter-1.md … chapter-N.md       # one per chapter (N per the contents list)
├── img/                              # extracted figures: img/chN-<seq>.<ext>
├── summary.md                        # human-read book summary (LLM-drafted, human-approved)
└── knowledge.yaml                    # machine-readable KB (schema in §6.5)
```

Plus repo root: `registry.yaml` (book_id → dir), `rag/` (§7.5), `pipeline/`, `prompts/`, `reports/`, `data/`, `docker-compose.yml`, `.env.example`.

### 4.1 `chapter-N.md`
Front matter (programmatic lookup surface — the "Notes for the Harness" contract):

```yaml
---
subject: Chemistry
board: ICSE
class: 10
section: "<board-syllabus unit containing this chapter>"   # D11
chapter: N
title: "<chapter title>"
syllabus:                 # canonical cleaned topic list for this chapter (GLOSSARY: Syllabus)
  - "<topic item>"
tags: [slug, ...]
file: chapter-N.md
provenance:               # added by this pipeline (POC parity + idempotency)
  source: Selina-Concise-Chemistry-10-chap-N.pdf
  sha256: <hash>
  docling_version: "1.26.0"
  pipeline: standard          # or vlm
  vlm_model: qwen3-vl:8b
  pages: <n>
  converted_at: 2026-11-14T…Z
---
```

Body rules: heading hierarchy mirrors the chapter's structure; images as `![](img/chN-001.png)` **followed** by their VLM description as a caption line; OCR artifacts tolerated in body (consumers may ignore per POC note) — but **captions are first-class text and must be kept**.

### 4.2 `chapters.md` (Chapter Index)
POC shape, chemistry content: `# / Section / Chapter Title / Syllabus (key points) / File` table + `Section → chapters` table + a *Notes for the Harness* block. The **Syllabus column is the lookup surface**: given a syllabus detail, the agent finds the Chapter via this table (exact, then fuzzy against `syllabus[]`/`tags`).

## 5. Conversion pipeline (`pipeline/convert`)

**Flow (per PDF chapter, batch = all chapters of a Book):**
1. Compute `sha256(PDF)` → if `chapter-N.md` exists, `provenance.sha256` matches and not `--force`: **skip** (idempotent).
2. `POST http://docling-serve:5001/v1/convert/file` (multipart), body params: `to_format=markdown`, `force_ocr=true`, `do_table_structure=true`, `include_images=true`, `pipeline=standard` (default) / `vlm` (override), `do_picture_description=true`, `picture_description_api={"url":"<OLLAMA>/v1/chat/completions","params":{"model":"<VLM_MODEL>"},"timeout":1200,"prompt":"Describe this technical illustration precisely for a chemistry student: every visible substance, apparatus, process step, labels and values."}`.
3. Response `document.md_content` → **normalize** (rewrite image refs into `img/chN-<seq>.<ext>`, extract image blobs from the converted document if embedded, strip HTML/encoding residue, fix heading levels) → write `chapter-N.md` with the §4.1 front matter.
4. Run **automated invariants** (gate A): non-empty; ≥1 `##` heading; every image ref has a caption line; no `U+FFFD`; `syllabus[]` non-empty (from the chapter head-list, cleaned) — failure ⇒ mark chapter `qa_failed`, continue batch.
5. Collect per-chapter record into `reports/convert-<UTCstamp>.jsonl` + a human summary (pass/fail/qa_failed/skipped + timings + docling model/version). **Non-zero exit** if any chapter failed.
6. Transient-only retries (connection reset/timeout), backoff 2s×3 (POC `converter.py` token list is the reference). Non-transient ⇒ fail the chapter, not the batch (D4).

**Chapter head-list → `syllabus[]`**: heuristic extraction (first list-like block after the chapter title heading, before the first content heading); on low confidence, one LLM-assisted clean pass (`prompts/clean-syllabus/`) with the same invariants — still deterministic *validation*.

## 6. Knowledge-base build (the "fully completed design")

Deterministic where structure allows; LLM (`qwen3.8:27b`) only where judgment is required (D6). Prompt + schema versions are recorded in every artifact's meta.

### 6.1 `pipeline/index` → `chapters.md`
Deterministic: merge chap-00 contents + each chapter's front matter (`section`, `title`, `syllabus[]`) → §4.2 tables. **Cross-check**: any chapter whose head-list topics disagree with its `syllabus[]` ⇒ flagged (not silently rewritten) into the report for the human gate.

### 6.2 `pipeline/summary` → `summary.md`
LLM-drafted (from all `chapter-N.md`, chapter-first, structure-preserving) → **human gate B** (approve/edit). This is the POC's "faithful source": `knowledge.yaml` must be a *faithful conversion* of `summary.md` + structure.

### 6.3 `pipeline/kb` → `knowledge.yaml`
Generated **from `summary.md` + `chapters.md` + chapter front matter** (not free-form), validated against `knowledge/schema/knowledge.yaml` (JSON-Schema over the YAML). Violations ⇒ `reports/quarantine-<stamp>.json` + one auto-retry with the violation text; anything still invalid is **excluded** (never guessed) and listed for the human.

**Chemistry entity set (D8-neutral, POC-shaped):**
`meta` · `thematic { one_liner[per chapter], themes, terms, substances, reactions, processes, laws, scientists }` · `timeline` (discovery/development entries) · `causal` (process & reasoning chains) · `cross_chapter` (relations incl. prerequisite/related — the graph edges, D7-stable IDs). *Deliberately absent:* `skills`, `harness` (ADR-0004).

**ID/anchor discipline (D7):** every entity carries `ch: [N,…]` chapter anchors (POC convention); slugs are `chem-icse10-…` and deterministic from canonical text, so a later cross-Book union is a merge, not a rework.

### 6.4 Validation gates (both books must pass before ingest)
- **Gate A** (per chapter, §5.4) — automatic.
- **Gate B** (`summary.md`) — human.
- **Gate C** (`knowledge.yaml`) — schema pass + all anchors resolve to existing chapters/topics + no dangling `cross_chapter` endpoints + entity counts per block ≥ 0 (empty blocks allowed, only when genuinely none).

## 7. RAG ingest (adopted POC `rag-spec.md`, service-free)

### 7.1 `registry.yaml` (repo root)
```yaml
books:
  - book_id: chemistry-icse10-selina
    dir: books/chemistry/ICSE-10thGrade
    subject: Chemistry
    board: ICSE
```
**Adding a book = one entry + folder drop + `ingest`.**

### 7.2 `rag/ingest`
Clean (strip `![]()` images & OCR noise, **keep captions**) → **structural chunk** (heading tree; syllabus blocks atomic) → `qwen3-embedding` via Ollama `/api/embed` (batched) → **`data/library.sqlite`**: `chunks` table + FTS5 + vector column; `chunk_id = sha1("{book_id}|{chapter}|{section}|{text}")`; **upsert + orphan-prune**; `book_id` filter mandatory on every query (D9).

### 7.3 `rag/retrieve` (the step-2 interface)
`retrieve(query, book_id, k)` → FTS5 ∥ vector, **RRF**-fused, de-duped, each hit carrying `chapter` + `section` + `topic[]` (from front matter) for citation. **No answer/LLM step in step 1** — that belongs to the step-2 workflows. Baselines (pure-FTS, pure-vector, hybrid) are computed here as *sanity checks*, not as the eval harness (D8).

### 7.4 Composition (`docker-compose.yml`, this repo)
```yaml
services:
  converter:                 # built from this repo (pipeline/ + rag/)
    network: docling-serve_default    # external (user's running project)
    environment:                      # also in .env.example
      DOCLING_URL: http://docling-serve:5001
      OLLAMA_URL: http://host.docker.internal:11434
      VLM_MODEL: qwen3-vl:8b          # D10
      FALLBACK_VLM_MODEL: granite3.2-vision:latest
      LLM_MODEL: qwen3.8:27b
      EMBED_MODEL: qwen3-embedding
    # `rag/ingest` & `rag/retrieve` run identically host-side (no container needed)
```
`converter` is the only new service; everything else (Ollama, docling-serve, sqlite) is host-side or a file (D5, D9).

> **Amendment (2026-11-15, Q13 — supersedes the `converter` service block above):** no service is built in this repo. `pipeline/` and `rag/` run **host-side Python** against the already-running docling-serve and Ollama, and `docling-serve` is treated strictly as an **external, never-replicated tracked dependency** (tracker ticket `school-prep-agent-x6h`, jointly managed): any VLM/model/timeout change is made in the `~/sandbox/docling-serve` project first, then re-pinned here (`.env.example` + §2), then the **Gate-0 pilot re-runs** on the next affected chapter before any batch continues. The tracker is a track, **never a gate** — no ticket may depend on it.

## 8. OpenCode harness (D6)

The **deterministic CLI** is the product: `python -m pipeline {convert,index,summary,kb,verify}` and `python -m rag {ingest,retrieve}`. The OpenCode session is the **operator**: runs stages in order, reads `reports/`, drives Gates B/C (presents failures, applies fixes, re-runs validation), and signs off the Book. LLM calls from the *agent* are limited to Gates B/C review and any repair of `summary.md`/`knowledge.yaml` — never to silently bypass a gate. This keeps the whole thing **locally executable with or without an agent** (the original requirement).

## 9. Acceptance for the Book (step 1 "done")

1. `chapters.md` + `chapter-1..N.md` all `pass` Gate A; every image has a caption.
2. `summary.md` approved (Gate B).
3. `knowledge.yaml` validates Gate C, anchors resolve, `thematic` non-empty for entities the book genuinely contains.
4. `rag/ingest` → `library.sqlite`; the **per-chapter query pack** (top-3 derived from `syllabus[]`; fallback L2 LLM clean pass → L3 chap-00 TOC/headings → L4 human, every entry `source:`-tagged — see ADR-0004 scope clarification) must hit **its own chapter first**, per chapter, via `rag/retrieve` — sweep report in `reports/evals-sweep-<stamp>.md`.
5. `reports/` contains the full run: what passed, what was quarantined, versions + hashes.

## 10. Deferred to step 2 (named, not designed)

- Skill-list contract + agentic student/instructor workflows (consume `knowledge.yaml` + `rag/retrieve`).
- Exam/`harness` block, question-pattern mining, gold-set eval (when the chemistry sample paper is provided).
- Cross-Book grading ladder merge (IDs are ready — ADR-0003).

## 11. Risks / mitigations

| Risk | Mitigation |
|---|---|
| docling standard pipeline weak on dense formula/figure chapters | `--pipeline vlm` escape hatch per chapter (D1) |
| Ollama VLM intermittency (long image prompts) | bounded retries, `timeout` in `picture_description_api`, per-chapter isolation (D4) |
| LLM over-generates KB entities not in the text | generated *only* from `summary.md`+chapters (6.3), anchors validated, quarantine-exclude (6.3) |
| Front-matter `syllabus[]` drifts from the head-list | index cross-check + Gate A (5, 6.1) |
| `granite3.2-vision` fallback weaker on chemistry notation | `VLM_MODEL=qwen3-vl:8b` default; caption invariant still enforced |

---

*Supersedes no prior document; extends `Requirements.md` with the locked decisions above. ADRs 0001–0004 and `GLOSSARY.md` are normative alongside this file.*
