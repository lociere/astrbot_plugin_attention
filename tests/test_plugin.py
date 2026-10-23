import unittest
from types import SimpleNamespace as NS

from fakes import At, AtAll, CommandFilter, Context, Event, Image, Plain, Reply, load_plugin
from test_windows import Clock

plugin_module = load_plugin()


class PluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.plugin = plugin_module.AttentionPlugin(Context(), {})
        self.plugin.windows.clock = self.clock

    async def wake(self, **kwargs):
        event = Event("你好", wake=True, chain=[Plain("月见你好")], **kwargs)
        await self.plugin.observe_message(event)
        return event

    def reply(self, text="好呀", role="assistant", is_chunk=False):
        return NS(role=role, completion_text=text, result_chain=None, is_chunk=is_chunk)

    async def test_unwoken_message_is_left_untouched(self):
        event = Event()
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)
        self.assertIsNone(event.get_extra(plugin_module.LEASE_EXTRA))
        self.assertEqual(event.message_str, "继续说吧")
        self.assertFalse(event.stopped)

    async def test_explicit_wake_then_normal_followup_preserves_message_chain(self):
        await self.wake()
        event = Event("真的吗？😋……")
        original = list(event.chain)
        await self.plugin.observe_message(event)
        self.assertTrue(event.is_at_or_wake_command)
        self.assertEqual(event.message_str, "真的吗？😋……")
        self.assertEqual(event.chain, original)

    async def test_different_sender_group_platform_or_bot_does_not_inherit_window(self):
        await self.wake()
        for identity in (
            {"user": "bob"},
            {"group": "other"},
            {"platform": "other"},
            {"bot": "other"},
        ):
            with self.subTest(identity=identity):
                event = Event(**identity)
                await self.plugin.observe_message(event)
                self.assertFalse(event.is_at_or_wake_command)

    async def test_window_expiry_does_not_cancel_existing_wake(self):
        await self.wake()
        self.clock.now = 190
        event = Event()
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)
        inherited = Event(wake=True)
        await self.plugin.observe_message(inherited)
        self.assertTrue(inherited.is_at_or_wake_command)

    async def test_at_and_quote_can_open_window(self):
        for chain in ([At("bot"), Plain("你好")], [Reply("bot"), Plain("你好")]):
            self.plugin.windows.clear()
            await self.plugin.observe_message(Event(wake=True, chain=chain))
            event = Event()
            await self.plugin.observe_message(event)
            self.assertTrue(event.is_at_or_wake_command)

    async def test_at_other_quote_other_unknown_quote_and_broadcast_not_promoted(self):
        await self.wake()
        for component in (At("bob"), Reply("bob"), Reply(None), AtAll()):
            with self.subTest(component=component):
                event = Event(chain=[component, Plain("你好")])
                await self.plugin.observe_message(event)
                self.assertFalse(event.is_at_or_wake_command)
        broadcast = Event(wake=True, chain=[AtAll(), Plain("通知")])
        await self.plugin.observe_message(broadcast)
        self.assertTrue(broadcast.is_at_or_wake_command)
        self.assertIsNone(broadcast.get_extra(plugin_module.LEASE_EXTRA))

    async def test_explicit_self_reference_wins_over_other_mentions(self):
        event = Event(wake=True, chain=[At("bot"), At("bob"), Plain("看看这个")])
        await self.plugin.observe_message(event)
        followup = Event()
        await self.plugin.observe_message(followup)
        self.assertTrue(followup.is_at_or_wake_command)

    async def test_core_suppressed_wake_cannot_open_window(self):
        event = Event(wake=False, chain=[At("bot"), Plain("你好")])
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)

    async def test_actual_command_does_not_open_window_or_change_dispatch(self):
        event = Event("reset", wake=True, chain=[Plain("/reset")])
        event.extras["activated_handlers"] = [NS(event_filters=[CommandFilter()])]
        await self.plugin.observe_message(event)
        self.assertTrue(event.is_at_or_wake_command)
        self.assertIsNone(event.get_extra(plugin_module.LEASE_EXTRA))
        next_event = Event()
        await self.plugin.observe_message(next_event)
        self.assertFalse(next_event.is_at_or_wake_command)

    async def test_slash_chat_without_command_handler_opens_window(self):
        event = Event("你好", wake=True, chain=[Plain("/你好")])
        await self.plugin.observe_message(event)
        followup = Event()
        await self.plugin.observe_message(followup)
        self.assertTrue(followup.is_at_or_wake_command)

    async def test_only_core_configured_prefixes_open_windows(self):
        event = Event("hello", wake=True, chain=[Plain("OtherBot hello")])
        await self.plugin.observe_message(event)
        self.assertIsNone(event.get_extra(plugin_module.LEASE_EXTRA))
        self.plugin.context.cfg["wake_prefix"] = ["", "Moon"]
        event = Event("hello", wake=True, chain=[Plain("Moon hello")])
        await self.plugin.observe_message(event)
        self.assertIsNotNone(event.get_extra(plugin_module.LEASE_EXTRA))

    async def test_empty_prefix_does_not_turn_all_messages_into_explicit_wakes(self):
        self.plugin.context.cfg["wake_prefix"] = [""]
        event = Event(wake=True)
        await self.plugin.observe_message(event)
        self.assertIsNone(event.get_extra(plugin_module.LEASE_EXTRA))

    async def test_private_self_stopped_and_missing_identity_are_ignored(self):
        for kwargs in ({"private": True}, {"user": "bot"}, {"group": ""}, {"platform": ""}):
            with self.subTest(kwargs=kwargs):
                event = await self.wake(**kwargs)
                self.assertIsNone(event.get_extra(plugin_module.LEASE_EXTRA))
        event = Event(wake=True, chain=[Plain("月见你好")])
        event.stopped = True
        await self.plugin.observe_message(event)
        self.assertIsNone(event.get_extra(plugin_module.LEASE_EXTRA))

    async def test_media_continuation_uses_existing_window(self):
        event = Event(text="", chain=[Image()])
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)
        await self.wake()
        await self.plugin.observe_message(event)
        self.assertTrue(event.is_at_or_wake_command)

    async def test_pure_mention_or_whitespace_does_not_promote_followup(self):
        await self.wake()
        for chain in ([Plain("  ")], [At("bot")], []):
            event = Event(text="", chain=chain)
            await self.plugin.observe_message(event)
            self.assertFalse(event.is_at_or_wake_command)

    async def test_response_and_normal_send_completion_both_extend_window(self):
        event = await self.wake()
        self.clock.now = 180
        await self.plugin.observe_reply(event, self.reply())
        self.clock.now = 200
        await self.plugin.after_reply(event)
        self.clock.now = 280
        event = Event()
        await self.plugin.observe_message(event)
        self.assertTrue(event.is_at_or_wake_command)
        self.clock.now = 290
        event = Event()
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)

    async def test_received_messages_without_replies_do_not_extend_window(self):
        await self.wake()
        self.clock.now = 180
        await self.plugin.observe_message(Event())
        self.clock.now = 191
        event = Event()
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)

    async def test_error_empty_tool_only_and_unrelated_replies_do_not_extend(self):
        event = await self.wake()
        self.clock.now = 180
        for reply in (self.reply("error", "err"), self.reply(""), self.reply("", "tool")):
            await self.plugin.observe_reply(event, reply)
        await self.plugin.observe_reply(Event(), self.reply())
        await self.plugin.after_reply(event)
        self.clock.now = 191
        followup = Event()
        await self.plugin.observe_message(followup)
        self.assertFalse(followup.is_at_or_wake_command)

    async def test_fixed_window_mode_does_not_extend_on_reply(self):
        self.plugin = plugin_module.AttentionPlugin(Context(), {"refresh_on_reply": False})
        self.plugin.windows.clock = self.clock
        event = await self.wake()
        self.clock.now = 180
        await self.plugin.observe_reply(event, self.reply())
        await self.plugin.after_reply(event)
        self.clock.now = 191
        followup = Event()
        await self.plugin.observe_message(followup)
        self.assertFalse(followup.is_at_or_wake_command)

    async def test_partial_stream_chunk_is_not_a_completed_answer(self):
        event = await self.wake()
        self.clock.now = 180
        await self.plugin.observe_reply(event, self.reply("一部分", is_chunk=True))
        await self.plugin.after_reply(event)
        self.clock.now = 191
        followup = Event()
        await self.plugin.observe_message(followup)
        self.assertFalse(followup.is_at_or_wake_command)

    async def test_late_reply_and_old_inflight_request_do_not_reopen_window(self):
        old = await self.wake()
        self.clock.now = 150
        await self.wake()
        self.clock.now = 180
        await self.plugin.observe_reply(old, self.reply())
        self.clock.now = 241
        followup = Event()
        await self.plugin.observe_message(followup)
        self.assertFalse(followup.is_at_or_wake_command)
        await self.plugin.observe_reply(old, self.reply())
        await self.plugin.after_reply(old)
        again = Event()
        await self.plugin.observe_message(again)
        self.assertFalse(again.is_at_or_wake_command)

    async def test_reload_cannot_reuse_old_event_lease(self):
        old = await self.wake()
        self.plugin = plugin_module.AttentionPlugin(Context(), {})
        self.plugin.windows.clock = self.clock
        await self.wake()
        self.clock.now = 180
        await self.plugin.observe_reply(old, self.reply())
        self.clock.now = 191
        event = Event()
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)

    async def test_config_disable_whitelist_and_media_switch(self):
        for config in ({"enabled": False}, {"allowed_groups": ["other"]}):
            self.plugin = plugin_module.AttentionPlugin(Context(), config)
            event = await self.wake()
            self.assertIsNone(event.get_extra(plugin_module.LEASE_EXTRA))
        self.plugin = plugin_module.AttentionPlugin(Context(), {"allow_media": False})
        self.plugin.windows.clock = self.clock
        await self.wake()
        event = Event(text="", chain=[Image()])
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)

    async def test_full_umo_allowlist_and_terminate(self):
        self.plugin = plugin_module.AttentionPlugin(
            Context(), {"allowed_groups": ["platform:GroupMessage:group"]}
        )
        event = await self.wake()
        self.assertIsNotNone(event.get_extra(plugin_module.LEASE_EXTRA))
        await self.plugin.terminate()
        event = Event()
        await self.plugin.observe_message(event)
        self.assertFalse(event.is_at_or_wake_command)
