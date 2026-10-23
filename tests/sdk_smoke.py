"""Exercise actual AstrBot dispatch with in-memory model / platform substitutes."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from astrbot import __version__  # noqa: E402
from astrbot.api.event import MessageEventResult  # noqa: E402
from astrbot.api.message_components import At, Image, Plain, Reply  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext  # noqa: E402
from astrbot.core.message.message_event_result import ResultContentType  # noqa: E402
from astrbot.core.pipeline.process_stage import stage as core_stage  # noqa: E402
from astrbot.core.pipeline.process_stage.method.star_request import (  # noqa: E402
    StarRequestSubStage,
)
from astrbot.core.platform.message_type import MessageType  # noqa: E402
from astrbot.core.provider.register import llm_tools  # noqa: E402
from astrbot.core.star.filter.command import CommandFilter  # noqa: E402
from astrbot.core.star.star import StarMetadata, star_map  # noqa: E402
from astrbot.core.star.star_handler import (  # noqa: E402
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)
from fakes import Event  # noqa: E402
from test_windows import Clock  # noqa: E402


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Context:
    def __init__(self):
        self.config = {
            "wake_prefix": ["/", "月见"],
            "provider_settings": {
                "enable": True,
                "identifier": False,
                "wake_prefix": "",
                "prompt_prefix": "{{prompt}}",
                "image_caption_prompt": "",
            },
            "provider_ltm_settings": {
                "group_message_max_cnt": 20,
                "image_caption": False,
                "active_reply": {
                    "enable": False,
                    "method": "possibility_reply",
                    "possibility_reply": 1.0,
                    "whitelist": [],
                },
            },
        }

    def get_config(self, **kwargs):
        return self.config

    def get_using_provider(self, *args, **kwargs):
        raise AssertionError("No real provider may be requested")


class SDKEvent(Event):
    def __init__(self, text="继续说吧", **kwargs):
        if "chain" not in kwargs:
            kwargs["chain"] = [Plain(text)]
        super().__init__(text, **kwargs)
        self._has_send_oper = False
        self.call_llm = False
        self.result = None

    def get_message_type(self):
        return MessageType.GROUP_MESSAGE

    def get_result(self):
        return self.result

    def set_result(self, result):
        self.result = result

    def clear_result(self):
        self.result = None


class InMemoryAgent:
    """Only this test substitute generates a reply; the plugin never does."""

    def __init__(self):
        self.calls = []

    async def process(self, event):
        self.calls.append((event.message_str, list(event.get_messages())))
        event.call_llm = True
        event.set_result(
            MessageEventResult()
            .message("in-memory answer")
            .set_result_content_type(ResultContentType.LLM_RESULT)
        )
        yield


async def smoke(emoji_plugin: Path | None):
    assert str(__version__).removeprefix("v").startswith("4.29.1"), __version__
    if emoji_plugin:
        load(emoji_plugin, "attention_smoke_emoji")
    tools_before = [(tool.name, id(tool)) for tool in llm_tools.func_list]
    module = load(ROOT / "main.py", "attention_sdk_smoke")
    assert [(tool.name, id(tool)) for tool in llm_tools.func_list] == tools_before
    if emoji_plugin:
        assert {"qq_native_emoji_search", "qq_native_emoji_send"}.issubset(
            name for name, _ in tools_before
        )

    context = Context()
    clock = Clock()
    plugin = module.AttentionPlugin(context, {})
    plugin.windows.clock = clock
    own = next(
        handler
        for handler in star_handlers_registry.get_handlers_by_event_type(
            EventType.AdapterMessageEvent
        )
        if handler.handler_module_path == "attention_sdk_smoke"
        and handler.handler_name == "observe_message"
    )
    own.handler = plugin.observe_message
    assert own.extras_configs["priority"] == sys.maxsize - 1

    group_context = GroupChatContext.__new__(GroupChatContext)
    group_context.context = context
    active_decisions = []

    async def ambient_handler(event):
        # Invoke the real built-in probability gate. The external model is never called.
        active = await group_context.need_active_reply(event)
        active_decisions.append(active)
        if active:
            yield ProviderRequest(prompt=event.message_str)

    ambient_path = "attention_sdk_ambient"
    star_map[ambient_path] = StarMetadata(name="in-memory ambient handler")
    ambient = StarHandlerMetadata(
        event_type=EventType.AdapterMessageEvent,
        handler_full_name=ambient_path,
        handler_name="ambient_handler",
        handler_module_path=ambient_path,
        handler=ambient_handler,
        event_filters=[],
    )

    stage = core_stage.ProcessStage()
    stage.ctx = NS(astrbot_config=context.config)
    stage.star_request_sub_stage = StarRequestSubStage()
    await stage.star_request_sub_stage.initialize(stage.ctx)
    stage.agent_sub_stage = InMemoryAgent()

    async def dispatch(event):
        event.set_extra("activated_handlers", [own, ambient])
        before = len(stage.agent_sub_stage.calls)
        async for _ in stage.process(event):
            pass
        return len(stage.agent_sub_stage.calls) - before

    # No active window and no background trigger: zero reply generations.
    assert await dispatch(SDKEvent("路过")) == 0

    # Core has already stripped the wake prefix from message_str, not from Plain.
    wake = SDKEvent("你好", wake=True, chain=[Plain("月见你好")])
    assert await dispatch(wake) == 1
    clock.now = 180
    await plugin.observe_reply(wake, LLMResponse("assistant", "好呀"))
    clock.now = 185
    await plugin.after_reply(wake)

    # Enabling core probability at 100% must not duplicate a follow-up reply.
    context.config["provider_ltm_settings"]["active_reply"]["enable"] = True
    followup = SDKEvent("真的吗？😋……")
    original_chain = list(followup.chain)
    assert await dispatch(followup) == 1
    assert active_decisions[-1] is False
    assert followup.message_str == "真的吗？😋……" and followup.chain == original_chain
    # The plugin does not silently suppress separately configured core probability.
    assert await dispatch(SDKEvent("其他成员发言", user="bob")) == 1
    assert active_decisions[-1] is True
    context.config["provider_ltm_settings"]["active_reply"]["enable"] = False
    assert await dispatch(SDKEvent("其他成员发言", user="bob")) == 0

    # A plain command name does not become an activated command merely by promotion.
    assert await dispatch(SDKEvent("reset")) == 1
    assert await dispatch(SDKEvent(chain=[At(qq="someone-else"), Plain("你好")])) == 0
    assert (
        await dispatch(SDKEvent(chain=[Reply(id="1", sender_id="someone-else"), Plain("你好")]))
        == 0
    )

    # Media messages are preserved for downstream media / emoji plugins.
    media = SDKEvent("", chain=[Image.fromURL("https://invalid.example/test-only.png")])
    assert await dispatch(media) == 1

    # A real core CommandFilter is recognized and left untouched.
    command = SDKEvent("reset", wake=True, chain=[Plain("/reset")])
    command.set_extra("activated_handlers", [NS(event_filters=[CommandFilter("reset")])])
    await plugin.observe_message(command)
    assert command.get_extra(module.LEASE_EXTRA) is None

    # Reply extension started at the send-completion hook; the original expiry is past.
    clock.now = 274
    assert await dispatch(SDKEvent()) == 1
    clock.now = 275
    assert await dispatch(SDKEvent()) == 0
    await plugin.terminate()
    print(
        json.dumps(
            {
                "astrbot": str(__version__),
                "sdk_load": "pass",
                "core_process_and_handler_dispatch": "pass",
                "core_probability_no_duplicate_reply": "pass",
                "commands_media_identity_and_expiry": "pass",
                "existing_emoji_tools_preserved": bool(emoji_plugin),
                "external_model_calls": 0,
                "platform_sends": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--emoji-plugin", type=Path)
    args = parser.parse_args()
    asyncio.run(smoke(args.emoji_plugin))
