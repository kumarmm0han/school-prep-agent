# Knowledge base is application-neutral at step 1

The POC (`school-prep-harness`) embeds consumer assumptions inside `knowledge.yaml` — a top-level `skills:` list naming the agentic workflows it serves, and a `harness` block (question types, high-yield facts, assertion-reason pairs, exam map) that presumes exam-prep consumption. We build the chemistry knowledge base **without either**: no `skills:` seed, no exam/`harness` block, no question-pattern mining.

**Why**: exam preparation is just *one* future application of the knowledge graph (student paths, instructor lesson planning, and the agentic workflows of step 2 are others). Baking one consumer's shape into the canonical artifact biases vocabulary and structure now, when the consumer set is unknown. The content blocks that *are* application-neutral — `meta`, `thematic` (incl. terms), `timeline`, `causal`, `cross_chapter` — carry the full substance; consumer-specific views (exam harness, skill lists, retrieval modes) attach in step 2 *against* this neutral base.

**Consequence**: `DESIGN.md` deliberately omits the eval/gold-set harness and the skill contract that the POC spec includes; they re-enter as step-2 work using the same `data/library.sqlite` and `knowledge.yaml`.
