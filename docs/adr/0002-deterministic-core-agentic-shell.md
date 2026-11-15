# Deterministic Python core, OpenCode as the agentic shell

The conversion, idempotency, QA-gates, graph-validation, chunking, and embedding pipeline are implemented as **deterministic Python** with no LLM calls in that path. LLMs appear only where judgment is required: figure description (docling's VLM pass) and knowledge-graph extraction (Topic/Term nodes, prerequisite/related edges) via `qwen3.8:27b`. The OpenCode session is the *operator*: it runs the pipeline, reviews QA reports, signs off chapters, and supervises extraction.

**Why**: a school-grade knowledge base must be reproducible and rerunnable — an agent-in-the-loop engine (option B considered) would make re-runs non-deterministic and the output hard to audit. Putting the LLM behind a strict schema + Python validator keeps generation free-form but storage disciplined.

**Consequence**: anything that must work without a running agent (CI, headless runs, the "locally executable" requirement) must live in the Python core.
