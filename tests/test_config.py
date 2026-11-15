"""Seam: config resolution from environment (DESIGN.md S2 defaults, env overrides)."""
import unittest


class ConfigDefaultsTest(unittest.TestCase):
    def test_defaults_match_design_s2(self):
        from pipeline.config import resolve_config

        cfg = resolve_config({})
        self.assertEqual(cfg.docling_url, "http://localhost:5001")
        self.assertEqual(cfg.ollama_url, "http://localhost:11434")
        self.assertEqual(cfg.vlm_model, "qwen3-vl:8b")
        self.assertEqual(cfg.fallback_vlm_model, "granite3.2-vision:latest")
        self.assertEqual(cfg.llm_model, "qwen3.8:27b")
        self.assertEqual(cfg.embed_model, "qwen3-embedding")

    def test_env_overrides_win_per_variable(self):
        from pipeline.config import resolve_config

        cfg = resolve_config(
            {
                "DOCLING_URL": "http://docling-serve:5001",
                "LLM_MODEL": "qwen3.6:35b",
            }
        )
        self.assertEqual(cfg.docling_url, "http://docling-serve:5001")
        self.assertEqual(cfg.llm_model, "qwen3.6:35b")
        # untouched variables keep design defaults
        self.assertEqual(cfg.vlm_model, "qwen3-vl:8b")
        self.assertEqual(cfg.ollama_url, "http://localhost:11434")

    def test_empty_string_does_not_override(self):
        from pipeline.config import resolve_config

        cfg = resolve_config({"EMBED_MODEL": ""})
        self.assertEqual(cfg.embed_model, "qwen3-embedding")


class FieldsTableDriftTest(unittest.TestCase):
    """The `_FIELDS` table and the `Config` dataclass must stay in lockstep."""

    def test_table_fields_match_dataclass_fields(self):
        import dataclasses

        from pipeline import config

        self.assertEqual(
            {f.name for f in dataclasses.fields(config.Config)},
            {name for name, _, _ in config._FIELDS},
        )

    def test_table_rows_are_complete(self):
        from pipeline import config

        for field, env_key, default in config._FIELDS:
            self.assertTrue(field, "empty field name in _FIELDS")
            self.assertTrue(env_key.startswith(("DOCLING", "OLLAMA", "VLM", "FALLBACK", "LLM", "EMBED")), env_key)
            self.assertTrue(default, f"empty default for {field}")


if __name__ == "__main__":
    unittest.main()
