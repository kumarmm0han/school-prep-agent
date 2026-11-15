# School-Prep Knowledge Base

The canonical language of the textbook corpus and the knowledge graphs agents use to locate, explain, and sequence chemistry content for students and instructors.

## Language

### Book content

**Book**:
One textbook for a subject and grade, e.g. Selina Concise Chemistry for ICSE grade 10.
_Avoid_: title, PDF set

**Chapter**:
A numbered, titled unit of a Book, each covering a scoped subject-area and opening with its own topic list.
_Avoid_: unit, lesson, PDF file

**Section**:
A board-syllabus unit (an ICSE topic module, e.g. class-10 Civics "I. The Union Legislature") that groups one or more Chapters; recorded in `chapters.md` and in chapter front matter.
_Avoid_: chapter (different level: Section ⋟ Chapter), heading block (an in-chapter text unit is not a Section)

**Syllabus**:
For a Chapter, the canonical cleaned list of its board-syllabus topics (CISCE 2025 wording); carried in chapter front matter and the `chapters.md` index; the source of truth for that chapter's Topics.
_Avoid_: outline, table of contents, the chapter's own OCR'd head-list (that is the raw input, not the canonical text)

**Figure description**:
The model-generated prose describing an illustration (reaction scheme, apparatus diagram), standing in for the picture in text-only contexts.
_Avoid_: alt text, OCR · _Note_: the conversion pipeline and Gate A call this line a **caption** / "caption line" per DESIGN S4.1/S5.4 — same thing.

### Knowledge graph

**Topic**:
One canonical syllabus item of a Chapter — the unit of learning the Chapter declares it teaches (e.g. *electrolysis*, *oxidation states*).
_Avoid_: concept, theme (a Theme spans chapters — different level), subject

**Theme**:
A cross-Chapter big idea in the knowledge base that synthesizes or cuts across several chapters (e.g. *separation of power* over Civics chapters 1–5).
_Avoid_: topic (chapter-scoped), summary, insight

**Term**:
A defined word or name in the text carrying a standard gloss (e.g. *valency*, *oxidising agent*).
_Avoid_: keyword, entity, vocabulary

**Chapter Index**:
The Book-level mapping between Chapters and each Chapter's topic list — the entry point an agent uses to route a learning goal to the right Chapter.
_Avoid_: table of contents (that is the book's page list), TOC

**Knowledge base** (`knowledge.yaml`):
The per-Book machine-readable semantic model — meta (sections→chapters map), thematic content (Theme, Term, plus discipline entities like substances and reactions), timeline, causal relations, cross-chapter relations, and the exam-harness block — the canonical structure the agentic skills consume.
_Avoid_: ontology, graph database (the *relations* in it are graph-shaped; the artifact is a document)

### Pipeline operations (step 1)

**Gate A**:
The automatic per-Chapter invariant pass (DESIGN S5.4, S6.4): body non-empty, at least one `##` heading, every image ref followed by a caption line, no `U+FFFD`, `syllabus[]` non-empty — plus the extended set (image blob files exist, `syllabus[]` count 2–15, well-formed heading hierarchy, no placeholder residue). A chapter that fails is recorded `qa_failed`; the batch continues (D4).
_Avoid_: lint, unit test, quality check

**qa_failed**:
A run-record status: the Chapter converted fine but violated one or more Gate A invariants. Distinct from `fail` (conversion itself failed, e.g. service/transient error) and `skipped` (idempotent skip — nothing to do).
_Avoid_: error, broken, rejected

**Book dir**:
The per-Book folder under `books/` the pipeline reads and writes (source PDFs, `chapter-*.md`, `img/`, `chapters.md`, `summary.md`, `knowledge.yaml`), one dir per Book (DESIGN S4).
_Avoid_: repo root, output dir, book package
