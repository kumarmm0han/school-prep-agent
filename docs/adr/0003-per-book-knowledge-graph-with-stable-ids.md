# Knowledge graphs are per-Book, with stable cross-mergeable node IDs

The knowledge graph is built **per Book** (one graph per textbook), not as one global corpus graph — even though the end goal includes cross-book sequencing (e.g. class-9 *atoms* → class-10 *electrolysis*). Node IDs are **stable and merge-friendly** from day one: `<subject>:<grade>:<node-kind>:<slug>` (e.g. `chem:icse10:topic:electrolysis`), generated deterministically from the canonical text.

**Why**: with a single book in the corpus today, a global graph is untestable (nothing to merge) and would force cross-book dedup assumptions before we have a second corpus to validate them against. Stable IDs make the later union a mechanical merge plus a reconciliation pass — not a rework.

**Considered (rejected for now)**: single global graph from day one; per-Book *directories* with no ID convention (loses the merge property).
