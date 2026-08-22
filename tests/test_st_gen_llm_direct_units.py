"""Unit tests for src/st_gen_llm_direct.py (E3S3T2).

Covers the deterministic Python-owned surface of the LLM-direct ST wrapper:
AST loading, output path resolution, message-content normalization, Markdown
fence cleanup, light ST structure validation, and the api-key guard on
generate_st(). No live inference calls are made.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import src.st_gen_llm_direct as st_llm


VALID_ST_TEXT = (
    "PROGRAM P\n"
    "VAR\n"
    "    X : BOOL;\n"
    "END_VAR\n"
    "IF X THEN\n"
    "    Y := TRUE;\n"
    "END_IF\n"
    "END_PROGRAM\n"
)


class LoadAstTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_valid_ast_loads(self) -> None:
        ast = st_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        self.assertGreater(len(ast.devices), 0)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            st_llm.load_ast(self.dir / "missing.json")

    def test_invalid_ast_raises_value_error(self) -> None:
        path = self.dir / "bad.json"
        path.write_text('{"not": "an ast"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            st_llm.load_ast(path)


class ResolveOutputPathTests(unittest.TestCase):
    def test_backend_specific_st_suffix(self) -> None:
        out = st_llm.resolve_output_path(Path("data/ast/signal_light_demo_api.json"), "api")
        self.assertEqual(
            out.name, "signal_light_demo_api_st_llm_direct_api.st"
        )
        out_local = st_llm.resolve_output_path(Path("data/ast/x.json"), "local")
        self.assertEqual(out_local.name, "x_st_llm_direct_local.st")


class MessageContentToTextTests(unittest.TestCase):
    def test_string_content_passthrough(self) -> None:
        self.assertEqual(st_llm._message_content_to_text("plain text"), "plain text")

    def test_list_of_strings_and_dicts(self) -> None:
        content = ["a", {"text": "b"}, {"content": "c"}, 42]
        self.assertEqual(st_llm._message_content_to_text(content), "a\nb\nc")

    def test_other_types_are_stringified(self) -> None:
        self.assertEqual(st_llm._message_content_to_text(123), "123")


class CleanLlmOutputTests(unittest.TestCase):
    def test_full_fence_is_stripped(self) -> None:
        raw = '```st\nPROGRAM P\nEND_PROGRAM\n```'
        self.assertEqual(st_llm.clean_llm_output(raw), "PROGRAM P\nEND_PROGRAM\n")

    def test_leading_fence_only_is_stripped(self) -> None:
        raw = "```\nPROGRAM P\nEND_PROGRAM"
        self.assertEqual(st_llm.clean_llm_output(raw), "PROGRAM P\nEND_PROGRAM\n")

    def test_trailing_fence_only_is_stripped(self) -> None:
        raw = "PROGRAM P\nEND_PROGRAM\n```"
        self.assertEqual(st_llm.clean_llm_output(raw), "PROGRAM P\nEND_PROGRAM\n")

    def test_plain_text_keeps_trailing_newline(self) -> None:
        self.assertEqual(st_llm.clean_llm_output("PROGRAM P"), "PROGRAM P\n")


class ValidateStStructureTests(unittest.TestCase):
    VALID = VALID_ST_TEXT

    def test_valid_structure_passes(self) -> None:
        st_llm.validate_st_structure(self.VALID)  # no raise

    def test_missing_required_token_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            st_llm.validate_st_structure("PROGRAM P\nVAR\nEND_VAR\n")
        self.assertIn("END_PROGRAM", str(ctx.exception))

    def test_end_program_before_program_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            st_llm.validate_st_structure(
                "END_PROGRAM\nPROGRAM P\nVAR\nEND_VAR\n"
            )
        self.assertIn("END_PROGRAM before PROGRAM", str(ctx.exception))

    def test_end_var_before_var_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            st_llm.validate_st_structure("PROGRAM P\nEND_VAR\nEND_PROGRAM\n")
        self.assertIn("END_VAR before VAR", str(ctx.exception))

    def test_unterminated_if_raises(self) -> None:
        text = "PROGRAM P\nVAR\nEND_VAR\nIF X THEN\n    Y := TRUE;\nEND_PROGRAM\n"
        with self.assertRaises(ValueError) as ctx:
            st_llm.validate_st_structure(text)
        self.assertIn("IF block", str(ctx.exception))

    def test_balanced_if_blocks_pass(self) -> None:
        text = (
            "PROGRAM P\nVAR\nEND_VAR\n"
            "IF A THEN\n    X := TRUE;\nEND_IF;\n"
            "IF B THEN\n    Y := TRUE;\nEND_IF\n"
            "END_PROGRAM\n"
        )
        st_llm.validate_st_structure(text)  # no raise

    def test_residual_code_fence_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            st_llm.validate_st_structure(self.VALID + "```\n")
        self.assertIn("code fences", str(ctx.exception))


class GenerateStTests(unittest.TestCase):
    def test_api_backend_without_key_raises(self) -> None:
        ast = st_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            with self.assertRaises(RuntimeError) as ctx:
                st_llm.generate_st(ast, Path("data/ast/x.json"), "api")
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    def _patched_llm(self, content: str):
        def fake_build_llm(backend):
            class Bound:
                def bind(self, **kwargs):
                    def invoke(_input):
                        return SimpleNamespace(content=content)

                    return invoke

            return Bound()

        return mock.patch.object(st_llm, "build_llm", side_effect=fake_build_llm)

    def test_generate_st_cleans_and_validates_local_output(self) -> None:
        valid = VALID_ST_TEXT
        ast = st_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        with self._patched_llm(f"```st\n{valid}```"):
            text = st_llm.generate_st(ast, Path("data/ast/x.json"), "local")
        self.assertEqual(text, valid if valid.endswith("\n") else valid + "\n")
        self.assertNotIn("```", text)

    def test_generate_st_rejects_invalid_output(self) -> None:
        ast = st_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        with self._patched_llm("PROGRAM P\nVAR\nEND_VAR\n"):  # no END_PROGRAM
            with self.assertRaises(ValueError):
                st_llm.generate_st(ast, Path("data/ast/x.json"), "local")

    def test_generate_st_wraps_invoke_failure(self) -> None:
        ast = st_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))

        def failing_invoke(_input):
            raise ConnectionError("server unreachable")

        def fake_build_llm(backend):
            class Bound:
                def bind(self, **kwargs):
                    return failing_invoke

            return Bound()

        with mock.patch.object(st_llm, "build_llm", side_effect=fake_build_llm):
            with self.assertRaises(RuntimeError) as ctx:
                st_llm.generate_st(ast, Path("data/ast/x.json"), "local")
        self.assertIn("LLM direct ST generation failed", str(ctx.exception))


class WriteStFileRoundtripTests(unittest.TestCase):
    def test_write_st_file_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path("data/ast/signal_light_demo_api_AST_C.json")
            valid = VALID_ST_TEXT

            def fake_build_llm(backend):
                class Bound:
                    def bind(self, **kwargs):
                        def invoke(_input):
                            return SimpleNamespace(content=valid)

                        return invoke

                return Bound()

            with (
                mock.patch.object(st_llm, "build_llm", side_effect=fake_build_llm),
                mock.patch.object(
                    st_llm, "DEFAULT_OUTPUT_DIR", Path(tmp)
                ) as out_dir,
            ):
                output_path = st_llm.write_st_file(src, "local")
            self.assertTrue(output_path.is_file())
            self.assertTrue(str(output_path).startswith(str(out_dir)))


if __name__ == "__main__":
    unittest.main()