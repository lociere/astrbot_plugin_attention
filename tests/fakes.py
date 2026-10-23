"""Minimal SDK-shaped doubles; sdk_smoke.py instead imports the real framework."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch


class Plain:
    def __init__(self, text):
        self.text = text


class At:
    def __init__(self, qq):
        self.qq = qq


class AtAll:
    pass


class Reply:
    def __init__(self, sender_id):
        self.sender_id = sender_id


class Image:
    pass


class CommandFilter:
    pass


class CommandGroupFilter:
    pass


class Star:
    def __init__(self, context):
        self.context = context


def decorator(*args, **kwargs):
    return lambda fn: fn


def load_plugin():
    modules = {}

    def add(name, **values):
        module = types.ModuleType(name)
        module.__dict__.update(values)
        modules[name] = module

    add("astrbot")
    add("astrbot.api", AstrBotConfig=dict)
    add(
        "astrbot.api.event",
        AstrMessageEvent=object,
        filter=types.SimpleNamespace(
            event_message_type=decorator,
            on_llm_response=decorator,
            after_message_sent=decorator,
            EventMessageType=types.SimpleNamespace(ALL="all"),
        ),
    )
    add("astrbot.api.message_components", Plain=Plain, At=At, AtAll=AtAll, Reply=Reply)
    add("astrbot.api.provider", LLMResponse=object)
    add("astrbot.api.star", Star=Star, Context=object, register=decorator)
    add("astrbot.core")
    add("astrbot.core.star")
    add("astrbot.core.star.filter")
    add("astrbot.core.star.filter.command", CommandFilter=CommandFilter)
    add("astrbot.core.star.filter.command_group", CommandGroupFilter=CommandGroupFilter)
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "attention_unit_test", root / "main.py", submodule_search_locations=[str(root)]
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**modules, spec.name: module}):
        spec.loader.exec_module(module)
    return module


class Context:
    def __init__(self, wake_prefix=None):
        self.cfg = {"wake_prefix": ["/", "月见"] if wake_prefix is None else wake_prefix}

    def get_config(self, **kwargs):
        return self.cfg

    def get_using_provider(self, *args, **kwargs):
        raise AssertionError("The attention plugin must never request a provider")


class Event:
    def __init__(
        self,
        text="继续说吧",
        *,
        wake=False,
        user="alice",
        group="group",
        platform="platform",
        bot="bot",
        chain=None,
        private=False,
    ):
        self.message_str = text
        self.chain = [Plain(text)] if chain is None else chain
        self.user, self.group, self.platform, self.bot = user, group, platform, bot
        self.private, self.stopped = private, False
        self.is_wake = True
        self.is_at_or_wake_command = wake
        self.extras = {"activated_handlers": []}
        self.unified_msg_origin = f"{platform}:GroupMessage:{group}"

    def is_private_chat(self):
        return self.private

    def is_stopped(self):
        return self.stopped

    def get_platform_id(self):
        return self.platform

    def get_self_id(self):
        return self.bot

    def get_group_id(self):
        return self.group

    def get_sender_id(self):
        return self.user

    def get_messages(self):
        return self.chain

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def send(self, *args, **kwargs):
        raise AssertionError("The attention plugin must never send messages")

    def request_llm(self, *args, **kwargs):
        raise AssertionError("The attention plugin must never request the LLM")

    def stop_event(self):
        raise AssertionError("The attention plugin must never stop propagation")
