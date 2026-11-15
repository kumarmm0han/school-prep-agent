# Conversion runs through the docling-serve HTTP API, not in-process docling

Two conversion paths existed: a local in-process `VlmPipeline` sample (`converter.py`) and the running `docling-serve` container plus the proven `markdown-wrapper` (`main.py`) that calls it. We build the pipeline against the **docling-serve HTTP API** (`/v1/convert/file`, V1.26 schema), using the wrapper's proven option set (`standard` pipeline, `force_ocr`, `do_table_structure`, `include_images`, picture-description via Ollama) — but called directly, with per-chapter option control.

**Why**: the conversion stack already exists as a service; calling it keeps one docling runtime, allows per-chapter overrides (OCR on/off, `pipeline` mode, VLM model) that the wrapper's fixed path cannot express, and reuses an option set empirically verified to return clean `md_content` on this docling version.

**Considered (rejected for this project)**:
- *In-process docling client* (`converter.py` style): heavier image, same runtime duplicated inside the converter, no upside for batched chapter work.
- *Routing through the existing `markdown-wrapper`*: convenient, but its options are fixed at deploy time, the picture-description model is hardcoded (and its `ibm/granite3.2-vision:2b` env tag does not exist in the running Ollama), and it hard-enables `do_picture_description`. The converter service owns its own request shape instead.
