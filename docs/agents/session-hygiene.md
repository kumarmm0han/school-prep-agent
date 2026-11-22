# Session & GPU Discipline

Rules for running this project's OpenCode/CLI sessions alongside the conversion
pipeline on this host. The script `scripts/convert_batch.sh` operationalizes the
pipeline rule; the session rules are for the operator (human or agent).

## Why: one GPU, two masters

This is a single-GPU DGX-Spark host (DESIGN S2). The agent's own inference runs
through Ollama (`qwen3.8:27b`) on that GPU, and so do the pipeline's models
(docling-serve standard/VLM conversion, `qwen3-vl:8b`, `qwen3-embedding`).
They share the device: a multi-hour book conversion started inside a coding
session queues behind — or starves — the model that is answering *right now*,
and a slow answer stalls the human reviewing the gates.

**Consequence:** conversion is a background job. Sessions control it
(launch / check / stop); they never run it inline.

## Rule 1 — pipeline runs go through the batch script, detached

```bash
scripts/convert_batch.sh start            # all books under books/ (default)
scripts/convert_batch.sh start --book-dir books/chemistry/ICSE-10thGrade
scripts/convert_batch.sh start --chapter 5          # one chapter per book
scripts/convert_batch.sh start --pipeline vlm       # D1 escape hatch
scripts/convert_batch.sh status           # running? tail the log
scripts/convert_batch.sh stop             # SIGTERM the batch (then SIGKILL)
scripts/convert_batch.sh start --foreground --chapter 99   # debug only: inline,
                                                           # visible, safe to abort
```

- The script runs `pipeline doctor` (read-only HTTP, zero GPU) before launching
  and refuses to start another batch while one is running (pidfile lock).
- Books convert **sequentially**; per-chapter isolation and idempotency are the
  engine's job (D4), so a `--force` re-run over an unchanged book is a no-op
  batch.
- Logs: `logs/batch/convert-batch-<stamp>.log` (+ `.pid`, `current`).
- Exit codes: 0 launched · 2 usage · 3 doctor failed · 4 already running.
- `--foreground` is for debugging a specific chapter/flag, never a book run.
- A session that *needs* a conversion: launch the batch, hand off, and check
  `status` + `reports/` in a LATER session.

## Rule 2 — one fresh session per task

- Start each ticket/task in a **fresh OpenCode session**; don't keep appending
  unrelated work to one long thread. Fresh context = cheaper turns, fewer
  stale assumptions.
- Prefer a **fresh git worktree** when the work is risky or long
  (`tools.opencode.worktree_create` / `git worktree add`): the main checkout
  stays clean, and sessions on different books/tickets can't stomp on each
  other's uncommitted edits.
- When a session must outlive its first task, run `/compact` before pivoting,
  and re-open only the file/ADR that the new task touches.

## Rule 3 — keep context lean

- **Never re-read a big file you've already read** in the session. Use
  `grep`/`glob` + a targeted `read` slice instead of re-opening
  `chapter-*.md`, `DESIGN.md` sections, or report JSONL in full.
- Prefer the small artifacts: `reports/*.status` one-liners,
  `bd show <id> --json`, `GLOSSARY.md` terms, ADR titles — pull the deep
  source only when deciding against it.
- Keep instructions lean: project rules live in `AGENTS.md` (short) + this
  doc; do not grow `AGENTS.md` with task details — that belongs in a bead
  ticket or a `docs/` file.
- Subagents for exploration, not context: an `explore`/`general` subagent
  reads the big files and returns a summary, so the main session stays small.

## Anti-patterns

| ❌ Don't | ✅ Do |
|---|---|
| `python -m pipeline convert --book-dir …` inside a session | `scripts/convert_batch.sh start …` (detached), hand off |
| Re-convert inline "while I'm here" to check a flag | `start --foreground --chapter N` on one chapter, read the record, done |
| One 10-hour session doing many tickets | One ticket per session/worktree; `/compact` before pivots |
| Re-reading 3000-line chapter markdown into context | grep it, or delegate to a subagent |
| Appending task notes to AGENTS.md | bead ticket (`bd create`) or `docs/` file |
