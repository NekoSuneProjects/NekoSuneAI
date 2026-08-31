import unittest

from nekosuneai import notifications
from nekosuneai.notifications import (
    PRIORITY_EMERGENCY,
    PRIORITY_IMPORTANT,
    PRIORITY_NORMAL,
    NotificationGate,
    classify_priority,
    parse_notify_command,
)


class PriorityTests(unittest.TestCase):
    def test_levels_map_to_priorities(self):
        self.assertEqual(classify_priority("weather is fine", "none"), PRIORITY_NORMAL)
        self.assertEqual(classify_priority("rain soon", "warning"), PRIORITY_IMPORTANT)
        self.assertEqual(classify_priority("fire", "danger"), PRIORITY_EMERGENCY)

    def test_government_broadcast_is_emergency(self):
        self.assertEqual(
            classify_priority("Government emergency broadcast: flood", "none"),
            PRIORITY_EMERGENCY,
        )


class CommandParsingTests(unittest.TestCase):
    def test_enable_dnd(self):
        self.assertEqual(parse_notify_command("turn on do not disturb"), ("dnd_on", None))

    def test_disable_dnd(self):
        self.assertEqual(parse_notify_command("disable quiet hours"), ("dnd_off", None))

    def test_set_quiet_window(self):
        action, value = parse_notify_command("set quiet hours from 10pm to 7am")
        self.assertEqual(action, "set_quiet")
        self.assertEqual(value, ("22:00", "07:00"))

    def test_recall_last(self):
        self.assertEqual(parse_notify_command("what did you just tell me?"), ("recall", None))

    def test_summary(self):
        self.assertEqual(parse_notify_command("what were the recent announcements"), ("summary", None))

    def test_unrelated_returns_none(self):
        self.assertIsNone(parse_notify_command("play some music"))


class _Clock:
    def __init__(self, start: float = 1_700_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class GateTests(unittest.TestCase):
    def setUp(self):
        # In-memory app_state so tests never touch the real SQLite DB.
        self._state: dict[str, str] = {}
        self._orig_get = notifications.get_state
        self._orig_set = notifications.set_state
        notifications.get_state = lambda key, default="": self._state.get(key, default)
        notifications.set_state = lambda key, value: self._state.update({key: value})
        self.clock = _Clock()
        # Use a fixed-offset zone-free window we control via clock; UTC-based tz.
        self.gate = NotificationGate("UTC", now_fn=self.clock)

    def tearDown(self):
        notifications.get_state = self._orig_get
        notifications.set_state = self._orig_set

    def test_duplicate_within_window_suppressed(self):
        self.assertTrue(self.gate.should_deliver("aircraft nearby", "none"))
        self.assertFalse(self.gate.should_deliver("aircraft nearby", "none"))

    def test_cooldown_between_distinct_but_repeated(self):
        self.assertTrue(self.gate.should_deliver("ping", "none"))
        self.clock.advance(200)  # past dedup window (120) but within nothing else
        self.assertTrue(self.gate.should_deliver("ping", "none"))

    def test_emergency_always_delivers_even_when_repeated(self):
        self.assertTrue(self.gate.should_deliver("Government emergency broadcast: flood", "none"))
        self.assertTrue(self.gate.should_deliver("Government emergency broadcast: flood", "none"))

    def test_quiet_hours_suppress_normal_but_not_emergency(self):
        # Enable DnD 22:00-07:00 and place the clock at 02:00 UTC.
        self.gate.handle("set quiet hours from 10pm to 7am")
        # 1_700_000_000 -> 2023-11-14 22:13:20 UTC (already inside window).
        self.assertFalse(self.gate.should_deliver("routine update", "none"))
        self.assertTrue(self.gate.should_deliver("Government emergency broadcast: flood", "danger"))

    def test_recall_reports_last_delivered(self):
        self.gate.should_deliver("the kettle boiled", "none")
        reply = self.gate.handle("what did you just tell me?")
        self.assertIn("the kettle boiled", reply)

    def test_summary_lists_recent(self):
        self.gate.should_deliver("first thing", "none")
        self.clock.advance(200)
        self.gate.should_deliver("second thing", "none")
        reply = self.gate.handle("recent announcements")
        self.assertIn("first thing", reply)
        self.assertIn("second thing", reply)

    def test_dnd_toggle_persists(self):
        self.gate.handle("turn on do not disturb")
        self.assertIn("on", self.gate.handle("do not disturb status").lower())
        self.gate.handle("turn off do not disturb")
        self.assertIn("off", self.gate.handle("do not disturb status").lower())

    def test_dont_interrupt_holds_while_active(self):
        self.gate.handle("don't interrupt me")
        self.gate.mark_activity(30)
        # Non-urgent alert is held while a conversation is active.
        self.assertFalse(self.gate.should_deliver("routine update", "none"))
        # Emergencies still get through.
        self.assertTrue(self.gate.should_deliver("Government emergency broadcast: flood", "danger"))

    def test_dont_interrupt_releases_after_window(self):
        self.gate.handle("don't interrupt me")
        self.gate.mark_activity(30)
        self.assertFalse(self.gate.should_deliver("update one", "none"))
        self.clock.advance(60)  # activity window elapsed
        self.assertTrue(self.gate.should_deliver("update two", "none"))


class DontInterruptParsingTests(unittest.TestCase):
    def test_enable(self):
        self.assertEqual(parse_notify_command("don't interrupt me"), ("interrupt_on", None))

    def test_disable(self):
        self.assertEqual(parse_notify_command("turn off do not interrupt"), ("interrupt_off", None))


if __name__ == "__main__":
    unittest.main()
