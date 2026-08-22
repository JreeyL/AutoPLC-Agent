"""Unit tests for src/req_parser.py (E3S3T2).

Covers the deterministic, offline-testable surface of the E2S1 requirement
parser: path resolution, argument parsing, backend LLM construction, and the
WSL host-IP helper. No live inference calls are made -- the LangChain client is
inspected structurally and network helpers are mocked.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import src.req_parser as req_parser


class ResolveOutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.requirements = self.base / "requirements"
        self.requirements.mkdir()
        self.input_path = self.requirements / "sample_control.txt"
        self.input_path.write_text("dummy", encoding="utf-8")

    def test_local_backend_maps_to_parsed_local(self) -> None:
        output = req_parser.resolve_output_path(self.input_path, "local")
        self.assertEqual(
            output, self.base / "parsed" / "sample_control_parsed_local.json"
        )

    def test_api_backend_maps_to_parsed_api(self) -> None:
        output = req_parser.resolve_output_path(self.input_path, "api")
        self.assertEqual(
            output, self.base / "parsed" / "sample_control_parsed_api.json"
        )

    def test_parsed_directory_is_created(self) -> None:
        self.assertFalse((self.base / "parsed").exists())
        req_parser.resolve_output_path(self.input_path, "api")
        self.assertTrue((self.base / "parsed").is_dir())

    def test_unknown_backend_suffix_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            req_parser.resolve_output_path(self.input_path, "bogus")

    def test_backend_suffix_mapping_matches_labels(self) -> None:
        self.assertEqual(req_parser.BACKEND_SUFFIX, {"local": "local", "api": "api"})


class ParseArgsTests(unittest.TestCase):
    def test_default_backend_is_local(self) -> None:
        with mock.patch.object(sys, "argv", ["req_parser", "data/x.txt"]):
            args = req_parser.parse_args()
        self.assertEqual(args.input_file, Path("data/x.txt"))
        self.assertEqual(args.backend, "local")

    def test_explicit_backend_is_honoured(self) -> None:
        with mock.patch.object(
            sys, "argv", ["req_parser", "data/x.txt", "--backend", "api"]
        ):
            args = req_parser.parse_args()
        self.assertEqual(args.backend, "api")

    def test_invalid_backend_choice_is_rejected(self) -> None:
        with mock.patch.object(
            sys, "argv", ["req_parser", "data/x.txt", "--backend", "bogus"]
        ):
            with self.assertRaises(SystemExit):
                req_parser.parse_args()


class GetWslHostIpTests(unittest.TestCase):
    def test_returns_gateway_ip_when_subprocess_succeeds(self) -> None:
        result = mock.Mock(stdout="172.18.32.1\n", stderr="")
        with mock.patch.object(subprocess, "run", return_value=result) as run:
            self.assertEqual(req_parser.get_wsl_host_ip(), "172.18.32.1")
        run.assert_called_once()

    def test_falls_back_to_localhost_when_output_is_empty(self) -> None:
        result = mock.Mock(stdout="   \n", stderr="")
        with mock.patch.object(subprocess, "run", return_value=result):
            self.assertEqual(req_parser.get_wsl_host_ip(), "localhost")

    def test_falls_back_to_localhost_on_subprocess_error(self) -> None:
        with mock.patch.object(
            subprocess, "run", side_effect=FileNotFoundError("no sh")
        ):
            self.assertEqual(req_parser.get_wsl_host_ip(), "localhost")

    def test_falls_back_to_localhost_on_nonzero_exit(self) -> None:
        with mock.patch.object(
            subprocess, "run", side_effect=subprocess.CalledProcessError(1, "ip")
        ):
            self.assertEqual(req_parser.get_wsl_host_ip(), "localhost")


class BuildLlmTests(unittest.TestCase):
    def test_local_backend_uses_lm_studio_surface(self) -> None:
        llm = req_parser.build_llm("local")
        self.assertEqual(llm.model_name, "local-model")
        self.assertEqual(llm.temperature, 0.0)
        self.assertTrue(llm.openai_api_base.endswith("/v1"))
        self.assertEqual(llm.openai_api_key.get_secret_value(), "lm-studio")

    def test_api_backend_uses_gemini_endpoint(self) -> None:
        with mock.patch.dict(
            os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False
        ):
            llm = req_parser.build_llm("api")
        self.assertEqual(llm.model_name, req_parser.GEMINI_MODEL)
        self.assertEqual(llm.openai_api_base, req_parser.GEMINI_BASE_URL)
        self.assertEqual(llm.openai_api_key.get_secret_value(), "test-key")
        self.assertEqual(llm.temperature, 0.0)

    def test_api_backend_without_key_exits(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            with self.assertRaises(SystemExit):
                req_parser.build_llm("api")

    def test_unknown_backend_falls_back_to_local(self) -> None:
        # The function has no explicit branch for unknown backends; anything
        # that is not "api" is treated as the local LM Studio target.
        llm = req_parser.build_llm("bogus")
        self.assertEqual(llm.model_name, "local-model")


if __name__ == "__main__":
    unittest.main()