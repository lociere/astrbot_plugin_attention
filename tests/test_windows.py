import unittest

from attention import AttentionWindow, Options, Scope


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.windows = AttentionWindow(90, 3, self.clock)
        self.scope = Scope("platform", "bot", "group", "alice")

    def test_deadline_is_exclusive_and_reads_do_not_extend_it(self):
        lease = self.windows.open(self.scope)
        for elapsed in (1, 50, 89.9):
            self.clock.now = 100 + elapsed
            self.assertEqual(self.windows.get(self.scope), lease)
        self.clock.now = 190
        self.assertIsNone(self.windows.get(self.scope))

    def test_reply_extends_from_current_time(self):
        lease = self.windows.open(self.scope)
        self.clock.now = 180
        self.assertTrue(self.windows.refresh(self.scope, lease))
        self.clock.now = 260
        self.assertEqual(self.windows.get(self.scope), lease)
        self.clock.now = 270
        self.assertIsNone(self.windows.get(self.scope))

    def test_all_four_identity_fields_are_isolated(self):
        self.windows.open(self.scope)
        for candidate in (
            Scope("different", "bot", "group", "alice"),
            Scope("platform", "different", "group", "alice"),
            Scope("platform", "bot", "different", "alice"),
            Scope("platform", "bot", "group", "different"),
        ):
            self.assertIsNone(self.windows.get(candidate))

    def test_late_reply_cannot_revive_expired_window(self):
        lease = self.windows.open(self.scope)
        self.clock.now = 191
        self.assertFalse(self.windows.refresh(self.scope, lease))
        self.assertIsNone(self.windows.get(self.scope))

    def test_old_reply_cannot_extend_a_newer_explicit_wake(self):
        old = self.windows.open(self.scope)
        self.clock.now = 150
        new = self.windows.open(self.scope)
        self.clock.now = 170
        self.assertFalse(self.windows.refresh(self.scope, old))
        self.assertTrue(self.windows.refresh(self.scope, new))

    def test_capacity_eviction_tracks_expiration_after_refresh(self):
        scopes = [Scope("p", "b", "g", str(i)) for i in range(4)]
        leases = [self.windows.open(scope) for scope in scopes[:3]]
        self.clock.now = 110
        self.windows.refresh(scopes[0], leases[0])
        self.windows.open(scopes[3])
        self.assertIsNotNone(self.windows.get(scopes[0]))
        self.assertIsNone(self.windows.get(scopes[1]))
        self.assertIsNotNone(self.windows.get(scopes[2]))

    def test_clear_invalidates_inflight_observations(self):
        old = self.windows.open(self.scope)
        self.windows.clear()
        self.assertFalse(self.windows.refresh(self.scope, old))
        new = self.windows.open(self.scope)
        self.assertNotEqual(new, old)


class ConfigTests(unittest.TestCase):
    def test_valid_values_and_group_id_normalization(self):
        options = Options.from_mapping(
            {"window_seconds": 120, "allowed_groups": [" 123 ", "123", "p:GroupMessage:1"]}
        )
        self.assertEqual(options.window_seconds, 120.0)
        self.assertEqual(options.allowed_groups, ("123", "p:GroupMessage:1"))

    def test_invalid_config_rejected_instead_of_silent_misbehavior(self):
        for config in (
            {"window_seconds": 0},
            {"window_seconds": float("nan")},
            {"window_seconds": float("inf")},
            {"window_seconds": "90"},
            {"window_seconds": True},
            {"enabled": "false"},
            {"max_sessions": 0},
            {"max_sessions": True},
            {"allowed_groups": "123"},
            {"allowed_groups": [123]},
            {"allowed_groups": [""]},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                Options.from_mapping(config)
