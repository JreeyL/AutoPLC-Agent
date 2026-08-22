"""Unit tests for src/ast_gen_C.py and src/ast_builders.py (E3S3T2).

Approach C drives deterministic builders through RPC/function-calling tool
calls. These tests cover the tool-call extraction/parsing layer, deterministic
grounding helpers, deterministic builders, fatal loading paths, grounding
checks on build_ast(), and the full build_ast() pipeline against the real
fixtures with a scripted fake LLM.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import src.ast_builders as ast_builders
import src.ast_gen_C as ast_gen_C
from src.ast_schemas import DeviceNode, InterlockNode, PLC_AST, SequenceStepNode


class ToolCallExtractionTests(unittest.TestCase):
    def test_extracts_call_from_tool_calls_with_dict_args(self) -> None:
        message = SimpleNamespace(
            tool_calls=[{"name": "build_sequence_step_node", "args": {"step_id": 1}}]
        )
        args = ast_gen_C._tool_call(message, "build_sequence_step_node", "seq 1")
        self.assertEqual(args["step_id"], 1)

    def test_extracts_call_from_additional_kwargs_openai_format(self) -> None:
        message = SimpleNamespace(
            tool_calls=[],
            additional_kwargs={
                "tool_calls": [
                    {
                        "function": {
                            "name": "build_interlock_node",
                            "arguments": '{"priority": 1}',
                        }
                    }
                ]
            },
        )
        args = ast_gen_C._tool_call(message, "build_interlock_node", "ilk 1")
        self.assertEqual(args["priority"], 1)

    def test_string_arguments_are_json_parsed(self) -> None:
        message = SimpleNamespace(
            tool_calls=[
                {
                    "name": "build_sequence_step_node",
                    "args": '{"step_id": 2, "action": "open EV-101"}',
                }
            ]
        )
        args = ast_gen_C._tool_call(message, "build_sequence_step_node", "seq")
        self.assertEqual(args["action"], "open EV-101")

    def test_wrong_call_count_raises(self) -> None:
        message = SimpleNamespace(
            tool_calls=[
                {"name": "build_sequence_step_node", "args": {}},
                {"name": "build_sequence_step_node", "args": {}},
            ]
        )
        with self.assertRaises(ValueError):
            ast_gen_C._tool_call(message, "build_sequence_step_node", "seq")

    def test_no_tool_calls_raises(self) -> None:
        with self.assertRaises(ValueError):
            ast_gen_C._tool_call(SimpleNamespace(tool_calls=[]), "any", "x")
        with self.assertRaises(ValueError):
            ast_gen_C._tool_call(SimpleNamespace(), "any", "x")

    def test_invalid_json_arguments_raise(self) -> None:
        message = SimpleNamespace(
            tool_calls=[
                {"name": "build_sequence_step_node", "args": "{not json"}]
        )
        with self.assertRaises(ValueError):
            ast_gen_C._tool_call(message, "build_sequence_step_node", "seq")

    def test_non_dict_arguments_raise(self) -> None:
        message = SimpleNamespace(
            tool_calls=[{"name": "build_sequence_step_node", "args": [1, 2]}]
        )
        with self.assertRaises(ValueError):
            ast_gen_C._tool_call(message, "build_sequence_step_node", "seq")


class ValidateChoiceTests(unittest.TestCase):
    def test_none_is_accepted(self) -> None:
        ast_gen_C._validate_choice(None, {"A"}, "target_device", "step")  # no raise

    def test_allowed_value_is_accepted(self) -> None:
        ast_gen_C._validate_choice("A", {"A", "B"}, "target_device", "step")

    def test_disallowed_value_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            ast_gen_C._validate_choice("C", {"A", "B"}, "target_device", "step")
        self.assertIn("not in equipment_list", str(ctx.exception))


class GroundingHelperTests(unittest.TestCase):
    EQUIPMENT = ["PMP-200", "SL-301"]

    def test_text_contains_name_boundary(self) -> None:
        self.assertTrue(ast_gen_C._text_contains_name("PMP-200 stalls", "PMP-200"))
        self.assertFalse(ast_gen_C._text_contains_name("PMP-2002 stalls", "PMP-200"))
        self.assertFalse(ast_gen_C._text_contains_name("XPMP-200 stalls", "PMP-200"))

    def test_find_mentioned_devices_respects_equipment_order(self) -> None:
        self.assertEqual(
            ast_gen_C._find_mentioned_devices("SL-301 and PMP-200 fail", self.EQUIPMENT),
            ["PMP-200", "SL-301"],
        )

    def test_find_mentioned_devices_empty(self) -> None:
        self.assertEqual(ast_gen_C._find_mentioned_devices("nothing", self.EQUIPMENT), [])


class BuilderTests(unittest.TestCase):
    def test_build_device_node(self) -> None:
        node = ast_builders.build_device_node("EV-101", "Valve")
        self.assertIsInstance(node, DeviceNode)
        self.assertEqual(node.node_id, "DEV-EV-101")
        self.assertEqual(node.source_equipment, "EV-101")

    def test_build_sequence_step_node_stamps_provenance(self) -> None:
        node = ast_builders.build_sequence_step_node(
            step_id=3,
            action="open EV-101",
            target_device="EV-101",
            condition="start pressed",
            source_scenario="Start system",
        )
        self.assertIsInstance(node, SequenceStepNode)
        self.assertEqual(node.node_id, "SEQ-3")
        self.assertEqual(node.source_step_id, 3)

    def test_build_interlock_node_stamps_verbatim_condition(self) -> None:
        node = ast_builders.build_interlock_node(
            index=2,
            condition="Emergency Stop pressed",
            forced_action="stop EV-101",
            affected_devices=["EV-101"],
            priority=1,
        )
        self.assertIsInstance(node, InterlockNode)
        self.assertEqual(node.node_id, "ILK-2")
        self.assertEqual(node.source_interlock_condition, "Emergency Stop pressed")
        self.assertEqual(node.affected_devices, ["EV-101"])

    def test_assemble_plc_ast_revalidates(self) -> None:
        device = ast_builders.build_device_node("EV-101", "Valve")
        step = ast_builders.build_sequence_step_node(1, "open EV-101")
        ilk = ast_builders.build_interlock_node(1, "E-stop", "close EV-101", ["EV-101"])
        ast = ast_builders.assemble_plc_ast(
            "Demo", [device], [step], [ilk], "req.json", "feat.feature"
        )
        self.assertIsInstance(ast, PLC_AST)
        self.assertEqual(ast.source_requirement_file, "req.json")


class LoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_load_requirement_missing_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            ast_gen_C.load_requirement(self.dir / "missing.json")

    def test_load_requirement_invalid_raises_value_error(self) -> None:
        path = self.dir / "bad.json"
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            ast_gen_C.load_requirement(path)

    def test_load_gherkin_missing_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            ast_gen_C.load_gherkin(self.dir / "missing.feature")

    def test_load_gherkin_empty_raises_value_error(self) -> None:
        path = self.dir / "empty.feature"
        path.write_text("   ", encoding="utf-8")
        with self.assertRaises(ValueError):
            ast_gen_C.load_gherkin(path)

    def test_load_gherkin_parse_failure_raises_value_error(self) -> None:
        path = self.dir / "broken.feature"
        path.write_text("Given a bare step without a feature", encoding="utf-8")
        with self.assertRaises(ValueError):
            ast_gen_C.load_gherkin(path)


class ResolveOutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.parsed = self.base / "parsed"
        self.parsed.mkdir()

    def test_maps_to_ast_c_suffix_with_backend(self) -> None:
        inp = self.parsed / "signal_light_demo_parsed_api.json"
        self.assertEqual(
            ast_gen_C.resolve_output_path(inp, "api"),
            self.base / "ast" / "signal_light_demo_api_AST_C.json",
        )

    def test_bad_name_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            ast_gen_C.resolve_output_path(self.parsed / "plain.json", "local")

    def test_ast_directory_is_created(self) -> None:
        ast_gen_C.resolve_output_path(self.parsed / "x_parsed_local.json", "local")
        self.assertTrue((self.base / "ast").is_dir())


class ScriptedFakeLLM:
    """Fake LLM that answers each bind_tools/invoke with a queued tool call."""

    def __init__(self, call_queue: list[dict]) -> None:
        self._queue = list(call_queue)
        self.bound_names: list[str] = []

    def bind_tools(self, tools, tool_choice=None):
        self.bound_names.append(tool_choice)

        def invoke(prompt):
            call = self._queue.pop(0)
            return SimpleNamespace(tool_calls=[{"name": call["name"], "args": call["args"]}])

        return SimpleNamespace(invoke=invoke)


class BuildAstTests(unittest.TestCase):
    REQ = Path("data/parsed/signal_light_demo_parsed_api.json")
    FEATURE = Path("data/gherkin/signal_light_demo_api.feature")

    def _equipment_names(self) -> list[str]:
        requirement = ast_gen_C.load_requirement(self.REQ)
        return [e.name for e in requirement.equipment_list]

    def _scenario_names(self) -> list[str]:
        _, scenarios = ast_gen_C.load_gherkin(self.FEATURE)
        return [s["name"] for s in scenarios]

    def test_build_ast_succeeds_with_scripted_tool_calls(self) -> None:
        requirement = ast_gen_C.load_requirement(self.REQ)
        equipment = self._equipment_names()
        scenarios = self._scenario_names()

        queue: list[dict] = []
        for source in requirement.sequences:
            queue.append(
                {
                    "name": "build_sequence_step_node",
                    "args": {
                        "step_id": source.step_id,
                        "action": source.description,
                        "target_device": equipment[0] if equipment else None,
                        "condition": "start pressed",
                        "source_scenario": scenarios[0],
                    },
                }
            )
        for index in range(1, len(requirement.interlocks) + 1):
            queue.append(
                {
                    "name": "build_interlock_node",
                    "args": {
                        "index": index,
                        "condition": "unused",
                        "forced_action": "unused",
                        "affected_devices": [equipment[0]] if equipment else [],
                        "source_scenario": scenarios[0],
                        "priority": 1,
                    },
                }
            )

        with mock.patch.object(ast_gen_C, "build_llm") as build_llm:
            build_llm.return_value = ScriptedFakeLLM(queue)
            ast = ast_gen_C.build_ast(self.REQ, self.FEATURE, "local")

        self.assertIsInstance(ast, PLC_AST)
        # Python overwrote authoritative source values despite tool suggestions.
        for node in ast.sequence:
            self.assertEqual(node.source_step_id, node.step_id)
            self.assertEqual(
                node.action,
                next(
                    s.description
                    for s in requirement.sequences
                    if s.step_id == node.step_id
                ),
            )
        for node in ast.interlocks:
            self.assertEqual(node.source_interlock_condition, node.condition)
            # Deterministic affected-device completion from authoritative text.
            combined = f"{node.condition} {node.forced_action}"
            mentioned = ast_gen_C._find_mentioned_devices(
                combined, self._equipment_names()
            )
            self.assertEqual(node.affected_devices, mentioned)

    def test_build_ast_rejects_unknown_target_device(self) -> None:
        requirement = ast_gen_C.load_requirement(self.REQ)
        queue = [
            {
                "name": "build_sequence_step_node",
                "args": {
                    "step_id": source.step_id,
                    "action": source.description,
                    "target_device": "NOT_A_DEVICE",
                },
            }
            for source in requirement.sequences
        ]
        with mock.patch.object(ast_gen_C, "build_llm") as build_llm:
            build_llm.return_value = ScriptedFakeLLM(queue)
            with self.assertRaises(ValueError) as ctx:
                ast_gen_C.build_ast(self.REQ, self.FEATURE, "api")
        self.assertIn("Grounding check failed", str(ctx.exception))

    def test_build_ast_rejects_unknown_source_scenario(self) -> None:
        requirement = ast_gen_C.load_requirement(self.REQ)
        queue = [
            {
                "name": "build_sequence_step_node",
                "args": {
                    "step_id": source.step_id,
                    "action": source.description,
                    "target_device": None,
                    "source_scenario": "Fabricated scenario",
                },
            }
            for source in requirement.sequences
        ]
        with mock.patch.object(ast_gen_C, "build_llm") as build_llm:
            build_llm.return_value = ScriptedFakeLLM(queue)
            with self.assertRaises(ValueError) as ctx:
                ast_gen_C.build_ast(self.REQ, self.FEATURE, "api")
        self.assertIn("is not a real Gherkin scenario", str(ctx.exception))

    def test_build_ast_rejects_unknown_affected_device(self) -> None:
        requirement = ast_gen_C.load_requirement(self.REQ)
        queue: list[dict] = [
            {
                "name": "build_sequence_step_node",
                "args": {
                    "step_id": source.step_id,
                    "action": source.description,
                },
            }
            for source in requirement.sequences
        ]
        for index in range(1, len(requirement.interlocks) + 1):
            queue.append(
                {
                    "name": "build_interlock_node",
                    "args": {
                        "index": index,
                        "condition": "unused",
                        "forced_action": "unused",
                        "affected_devices": ["GHOST_DEVICE"],
                    },
                }
            )
        with mock.patch.object(ast_gen_C, "build_llm") as build_llm:
            build_llm.return_value = ScriptedFakeLLM(queue)
            with self.assertRaises(ValueError) as ctx:
                ast_gen_C.build_ast(self.REQ, self.FEATURE, "api")
        self.assertIn("is not a subset of equipment_list", str(ctx.exception))

    def test_build_ast_propagates_tool_invocation_failures(self) -> None:
        requirement = ast_gen_C.load_requirement(self.REQ)
        queue = [
            {
                "name": "build_sequence_step_node",
                "args": {
                    "step_id": source.step_id,
                    "action": source.description,
                },
            }
            for source in requirement.sequences
        ]
        queue[0] = queue[0] | {"args": []}  # non-dict args -> ValueError inside
        with mock.patch.object(ast_gen_C, "build_llm") as build_llm:
            build_llm.return_value = ScriptedFakeLLM(queue)
            with self.assertRaises(RuntimeError):
                ast_gen_C.build_ast(self.REQ, self.FEATURE, "local")

    def test_scenario_context_is_json_serializable(self) -> None:
        _, scenarios = ast_gen_C.load_gherkin(self.FEATURE)
        context = ast_gen_C._scenario_context(scenarios)
        decoded = json.loads(context)
        self.assertEqual(decoded[0]["name"], scenarios[0]["name"])


if __name__ == "__main__":
    unittest.main()