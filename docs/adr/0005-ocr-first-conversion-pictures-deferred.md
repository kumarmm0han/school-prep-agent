# OCR-first conversion: picture content deferred (owner decision 2026-11-15)

The s3c frozen option set carried `do_picture_description=true` + `picture_description_api` (VLM captions). The `agp` engine proof on the real `chap-1` proved that captions are **silently dropped by the running service**: docling-serve 1.26 marks `picture_description_api` DEPRECATED (ignored), the replacement `picture_description_custom_config` is gated by `allow_custom_picture_description_config` (default `false`, an SSRF guard the container does not override), and docling_slim 2.113's `PictureDescriptionApiOptions` has **no `prompt` field** — so the DESIGN caption prompt would need a service-side home (preset or params) that does not exist yet.

The book owner reviewed the evidence on 2026-11-15 and decided: **the book is text-focused; for now an OCR conversion is good enough**. No reconfiguration of the shared service for one book's marginal figures.

**Decision (contract v2, pinned in `pipeline/docling_client.build_form`):**

- `to_format=markdown`, `force_ocr=true`, `do_table_structure=true`, `include_images=false`, `pipeline=standard|vlm` — and **nothing else**.
- `include_images=false` keeps the markdown picture-free (docling-serve defaults it to `true`, so it is sent explicitly). The `<!-- image -->` residue is stripped by 1qm's normalizer, and Gate A's image rules (caption line, blob existence) are vacuous on picture-free markdown.
- The picture machinery that already exists — `imgseq` shared contract, `images.extract`, the img/ layout — is **kept, not deleted**: it is the live path the moment pictures are re-enabled.
- The deferred shapes (caption prompt, Ollama endpoint, `VLM_MODEL`, inner timeout, the `picture_description_custom_config`/preset decision) are carried by ticket **`school-prep-agent-ezq`** (deferred), which unblocks the re-enable. `x6h` (service track) returns to P4. `VLM_MODEL`/`FALLBACK_VLM_MODEL` stay pinned in S2 for that day.

**Why not fix the service instead:** captions were proven broken in three independent places (deprecated param, SSRF gate, missing prompt field); making them work is a service + contract redesign (x6h + ezq), while the owner's actual need — clean, QA-passing text chapters — is met by the OCR path. Ship the book; revisit pictures when (if) the content calls for it.

**Reversing this decision:** land ezq (client contract v3 per the service's enabled shape) → Gate A's caption rule automatically re-applies to any chapter that carries image refs → re-run the pilot. No engine change required.
