import ast
import json
import unittest
from dataclasses import fields
from pathlib import Path

import yaml

from attention import Options

ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_metadata_and_schema_agree_with_runtime(self):
        metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["name"], "astrbot_plugin_attention")
        self.assertEqual(metadata["version"], "0.1.0")
        self.assertEqual(metadata["support_platforms"], ["aiocqhttp"])
        self.assertEqual(set(schema), {item.name for item in fields(Options)})
        configured = Options.from_mapping({key: value["default"] for key, value in schema.items()})
        self.assertEqual(configured, Options())

    def test_production_code_has_no_reply_or_context_takeover_api(self):
        prohibited = {
            "send",
            "send_streaming",
            "send_message",
            "call_action",
            "request_llm",
            "text_chat",
            "stop_event",
            "set_result",
            "clear_result",
            "get_using_provider",
            "get_using_provider_async",
            "llm_generate",
            "monkeypatch",
        }
        for filename in ("main.py", "attention.py"):
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, prohibited, filename)
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                            if target.value.id == "event":
                                self.assertEqual(target.attr, "is_at_or_wake_command")
