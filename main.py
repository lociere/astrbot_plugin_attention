"""Add bounded follow-up wake eligibility; leave reply generation to AstrBot."""

from __future__ import annotations

from sys import maxsize

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, AtAll, Plain, Reply
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter

from .attention import AttentionWindow, Options, Scope

NAME = "astrbot_plugin_attention"
VERSION = "0.1.0"
LEASE_EXTRA = f"{NAME}:lease"
REPLY_EXTRA = f"{NAME}:has_reply"

# After the built-in session waiter, before group-context / probability handlers.
# Verified against AstrBot 4.29.1; no framework handler is replaced or wrapped.
LISTENER_PRIORITY = maxsize - 1


@register(NAME, "lociere", "按成员限时续聊，仅补充唤醒标记", VERSION)
class AttentionPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.options = Options.from_mapping(config)
        self.windows = AttentionWindow(self.options.window_seconds, self.options.max_sessions)

    def _scope(self, event: AstrMessageEvent) -> Scope | None:
        if not self.options.enabled or event.is_private_chat() or event.is_stopped():
            return None
        platform, bot = str(event.get_platform_id() or ""), str(event.get_self_id() or "")
        group, user = str(event.get_group_id() or ""), str(event.get_sender_id() or "")
        if not all((platform, bot, group, user)) or bot == user:
            return None
        allowed = self.options.allowed_groups
        if allowed and group not in allowed and event.unified_msg_origin not in allowed:
            return None
        return Scope(platform, bot, group, user)

    @staticmethod
    def _is_command(event: AstrMessageEvent) -> bool:
        # WakingCheckStage has already resolved actual commands with the active
        # configuration's prefixes. Do not mistake ordinary /chat for a command.
        return any(
            isinstance(flt, (CommandFilter, CommandGroupFilter))
            for handler in event.get_extra("activated_handlers", [])
            for flt in handler.event_filters
        )

    @staticmethod
    def _references(event: AstrMessageEvent, bot: str) -> tuple[bool, bool]:
        to_self, to_other = False, False
        for component in event.get_messages():
            if isinstance(component, AtAll):
                to_other = True
            elif isinstance(component, At):
                if str(component.qq) == bot:
                    to_self = True
                else:
                    to_other = True
            elif isinstance(component, Reply):
                if str(component.sender_id) == bot:
                    to_self = True
                else:
                    to_other = True
        return to_self, to_other

    def _explicit_wake(self, event: AstrMessageEvent, to_self: bool) -> bool:
        # Require the existing core decision too; never revive a wake explicitly
        # suppressed by another earlier handler.
        if not event.is_at_or_wake_command:
            return False
        if to_self:
            return True
        config = self.context.get_config(umo=event.unified_msg_origin)
        original_text = "".join(
            part.text for part in event.get_messages() if isinstance(part, Plain)
        ).strip()
        return any(
            isinstance(prefix, str) and prefix and original_text.startswith(prefix)
            for prefix in config.get("wake_prefix", [])
        )

    @filter.event_message_type(filter.EventMessageType.ALL, priority=LISTENER_PRIORITY)
    async def observe_message(self, event: AstrMessageEvent) -> None:
        """只记录明确唤醒，或为有效续聊消息补充唤醒标记。"""
        scope = self._scope(event)
        if scope is None or self._is_command(event):
            return
        to_self, to_other = self._references(event, scope.bot)
        explicit = self._explicit_wake(event, to_self)
        if self.options.ignore_addressed_to_others and to_other and not explicit:
            return
        chain = event.get_messages()
        has_text = any(isinstance(part, Plain) and part.text.strip() for part in chain)
        has_media = any(not isinstance(part, (Plain, At, AtAll, Reply)) for part in chain)
        if not has_text and not (self.options.allow_media and has_media):
            return

        # Opening is tied to an explicit wake. Follow-ups and background group
        # traffic do not refresh a window merely by arriving.
        lease = self.windows.open(scope) if explicit else self.windows.get(scope)
        if lease is None:
            return
        event.set_extra(LEASE_EXTRA, (self.windows, scope, lease))
        if not explicit:
            event.is_at_or_wake_command = True

    @filter.on_llm_response()
    async def observe_reply(self, event: AstrMessageEvent, response: LLMResponse) -> None:
        """模型完成实际回答后续时，也覆盖流式结果不触发发送后钩子的情况。"""
        if not self.options.refresh_on_reply or self._scope(event) is None:
            return
        lease = event.get_extra(LEASE_EXTRA)
        if (
            lease is None
            or lease[0] is not self.windows
            or response.role != "assistant"
            or response.is_chunk
        ):
            return
        if not (response.completion_text or "").strip() and not (
            response.result_chain and response.result_chain.chain
        ):
            return
        if self.windows.refresh(*lease[1:]):
            event.set_extra(REPLY_EXTRA, True)

    @filter.after_message_sent()
    async def after_reply(self, event: AstrMessageEvent) -> None:
        """普通回复发送阶段结束后再续时，包含分段发送花费的时间。"""
        if not self.options.refresh_on_reply or self._scope(event) is None:
            return
        lease = event.get_extra(LEASE_EXTRA)
        if lease is not None and lease[0] is self.windows and event.get_extra(REPLY_EXTRA, False):
            self.windows.refresh(*lease[1:])

    async def terminate(self) -> None:
        self.windows.clear()
