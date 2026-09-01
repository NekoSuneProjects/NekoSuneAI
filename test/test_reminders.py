import unittest
import time
from zoneinfo import ZoneInfo

from nekosuneai import reminders
from nekosuneai.reminders import ReminderManager, parse_reminder_request


class ReminderParsingTests(unittest.TestCase):
    def test_named_timer_controls(self):
        self.assertEqual(parse_reminder_request("pause the pasta timer", ZoneInfo("Europe/London"))[0], "pause")
        self.assertEqual(parse_reminder_request("resume pasta timer", ZoneInfo("Europe/London"))[0], "resume")
        self.assertEqual(parse_reminder_request("cancel pasta timer", ZoneInfo("Europe/London"))[0], "remove")

    def test_repeating_alarm_and_snooze_parsing(self):
        action,item=parse_reminder_request("set an alarm at 7 AM every weekday called work",ZoneInfo("Europe/London"))
        self.assertEqual(action,"create")
        self.assertEqual(item.repeat_pattern,"weekdays")
        self.assertEqual(parse_reminder_request("snooze work alarm for 10 minutes",ZoneInfo("Europe/London"))[0],"snooze")

    def test_temporary_alarm_and_location_reminder_parsing(self):
        action,item=parse_reminder_request("for the next three days, wake me at 8",ZoneInfo("Europe/London"))
        self.assertEqual(action,"create")
        self.assertEqual(item.repeat_pattern,"daily")
        self.assertGreater(item.repeat_until_epoch,item.due_epoch)
        action,item=parse_reminder_request("remind me about washing when I next go downstairs",ZoneInfo("Europe/London"))
        self.assertEqual(action,"create")
        self.assertEqual(item.trigger_room,"downstairs")


class ReminderManagerTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        self.notifications = []
        self.orig_load, self.orig_save = reminders._load, reminders._save
        reminders._load = lambda: list(self.rows)
        reminders._save = lambda rows: setattr(self, "rows", list(rows))
        self.manager = ReminderManager(lambda message, level: self.notifications.append((message, level)))

    def tearDown(self):
        reminders._load, reminders._save = self.orig_load, self.orig_save

    def test_pause_resume_and_cancel_named_timer(self):
        self.manager.handle("set a timer for 20 minutes called pasta")
        self.assertIn("Paused pasta timer", self.manager.handle("pause pasta timer"))
        self.assertFalse(self.rows[0].active)
        self.assertGreater(self.rows[0].paused_remaining_seconds, 0)
        self.assertIn("paused", self.manager.handle("show my timers"))
        self.assertIn("Resumed pasta timer", self.manager.handle("resume pasta timer"))
        self.assertTrue(self.rows[0].active)
        self.assertIn("Cancelled", self.manager.handle("cancel pasta timer"))
        self.assertFalse(self.rows[0].active)

    def test_duplicate_names_require_id(self):
        self.manager.handle("set a timer for 10 minutes called tea")
        self.manager.handle("set a timer for 20 minutes called tea")
        self.assertIn("more than one", self.manager.handle("pause tea timer"))
        item_id = self.rows[0].id
        self.assertIn("Paused", self.manager.handle(f"pause timer {item_id}"))

    def test_due_timer_delivers_warning_once(self):
        self.manager.handle("set a timer for 1 second called oven")
        self.assertEqual(self.manager._fire_due_once(time.time() + 2), 1)
        self.assertEqual(self.notifications, [("Timer: oven timer is finished", "warning")])
        self.assertEqual(self.manager._fire_due_once(time.time() + 3), 0)

    def test_repeating_alarm_reschedules_and_can_snooze(self):
        self.manager.handle("set an alarm at 7 AM every day called work")
        original_due=self.rows[0].due_epoch
        self.manager._fire_due_once(original_due+1)
        self.assertTrue(self.rows[0].active)
        self.assertGreater(self.rows[0].due_epoch,original_due)
        self.assertIn("Snoozed work alarm",self.manager.handle("snooze work alarm for 10 minutes"))
        self.assertAlmostEqual(self.rows[0].due_epoch,time.time()+600,delta=2)

    def test_dismiss_turns_off_repeat(self):
        self.manager.handle("set an alarm at 7 AM every day called work")
        self.assertIn("Dismissed work alarm",self.manager.handle("dismiss work alarm"))
        self.assertFalse(self.rows[0].active)
        self.assertEqual(self.rows[0].repeat_pattern,"")

    def test_temporary_alarm_stops_after_final_day(self):
        self.manager.handle("for the next 2 days, wake me at 8")
        first=self.rows[0].due_epoch
        self.assertEqual(self.manager._fire_due_once(first+1),1)
        second=self.rows[0].due_epoch
        self.assertTrue(self.rows[0].active)
        self.assertEqual(self.manager._fire_due_once(second+1),1)
        self.assertFalse(self.rows[0].active)

    def test_location_reminder_fires_once_on_matching_occupancy(self):
        reply=self.manager.handle("remind me about washing when I next go downstairs")
        self.assertIn("when you next enter downstairs",reply)
        self.assertEqual(self.manager.handle_event("presence.changed",{"presence":{"room":"upstairs","occupied":True}}),0)
        self.assertEqual(self.manager.handle_event("presence.changed",{"presence":{"room":"downstairs","occupied":True}}),1)
        self.assertEqual(self.notifications,[("Reminder: washing","warning")])
        self.assertEqual(self.manager.handle_event("presence.changed",{"presence":{"room":"downstairs","occupied":True}}),0)


if __name__ == "__main__":
    unittest.main()
