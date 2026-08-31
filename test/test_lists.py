import unittest
from zoneinfo import ZoneInfo

from nekosuneai import lists
from nekosuneai.lists import ListItem, ListManager, parse_list_request

TZ = ZoneInfo("Europe/London")


class ListParsingTests(unittest.TestCase):
    def test_add_single_shopping_item(self):
        action, payload = parse_list_request("add milk to my shopping list", TZ)
        self.assertEqual(action, "add")
        self.assertEqual(payload["list"], "shopping")
        self.assertEqual([i.text for i in payload["items"]], ["milk"])

    def test_add_multiple_shopping_items(self):
        action, payload = parse_list_request("add eggs, bread and butter to the shopping list", TZ)
        self.assertEqual(action, "add")
        self.assertEqual([i.text for i in payload["items"]], ["eggs", "bread", "butter"])

    def test_add_todo_with_priority(self):
        action, payload = parse_list_request("add call the dentist to my to-do list, high priority", TZ)
        self.assertEqual(action, "add")
        self.assertEqual(payload["list"], "todo")
        item = payload["items"][0]
        self.assertEqual(item.text, "call the dentist")
        self.assertEqual(item.priority, "high")

    def test_add_todo_with_due_day(self):
        action, payload = parse_list_request("add finish the report to my todo list by friday", TZ)
        item = payload["items"][0]
        self.assertEqual(item.text, "finish the report")
        self.assertGreater(item.due_epoch, 0.0)

    def test_urgent_alias_maps_to_urgent(self):
        _, payload = parse_list_request("add pay rent to my task list asap", TZ)
        self.assertEqual(payload["items"][0].priority, "urgent")

    def test_show_shopping(self):
        self.assertEqual(parse_list_request("what's on my shopping list", TZ), ("show", {"list": "shopping"}))

    def test_show_todo(self):
        self.assertEqual(parse_list_request("show my to-do list", TZ), ("show", {"list": "todo"}))

    def test_remove_item(self):
        action, payload = parse_list_request("remove milk from my shopping list", TZ)
        self.assertEqual(action, "remove")
        self.assertEqual(payload["items"], ["milk"])

    def test_check_off_item(self):
        action, payload = parse_list_request("check off eggs from my shopping list", TZ)
        self.assertEqual(action, "complete")
        self.assertIn("eggs", payload["items"])

    def test_clear_list(self):
        action, payload = parse_list_request("clear my shopping list", TZ)
        self.assertEqual(action, "clear")
        self.assertEqual(payload["list"], "shopping")

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(parse_list_request("what's the weather like today", TZ))


class ListManagerTests(unittest.TestCase):
    def setUp(self):
        # Keep storage in memory so tests never touch the real SQLite DB.
        self._store = lists._empty_store()
        self._orig_load = lists._load
        self._orig_save = lists._save
        lists._load = lambda: {k: list(v) for k, v in self._store.items()}
        lists._save = lambda store: self._store.update({k: list(v) for k, v in store.items()})
        self.mgr = ListManager("Europe/London")

    def tearDown(self):
        lists._load = self._orig_load
        lists._save = self._orig_save

    def test_add_then_show_shopping(self):
        self.mgr.handle("add milk and eggs to my shopping list")
        reply = self.mgr.handle("what's on my shopping list")
        self.assertIn("milk", reply)
        self.assertIn("eggs", reply)

    def test_remove_updates_list(self):
        self.mgr.handle("add milk to my shopping list")
        reply = self.mgr.handle("remove milk from my shopping list")
        self.assertIn("Removed milk", reply)
        self.assertIn("empty", self.mgr.handle("show my shopping list"))

    def test_completed_todo_hidden_from_show(self):
        self.mgr.handle("add call dentist to my to-do list")
        self.mgr.handle("check off call dentist")
        self.assertIn("empty", self.mgr.handle("show my to-do list"))

    def test_todo_sorted_by_priority(self):
        self.mgr.handle("add water plants to my to-do list, low priority")
        self.mgr.handle("add pay rent to my to-do list, urgent")
        reply = self.mgr.handle("show my to-do list")
        self.assertLess(reply.index("pay rent"), reply.index("water plants"))

    def test_clear_reports_count(self):
        self.mgr.handle("add milk and eggs to my shopping list")
        reply = self.mgr.handle("clear my shopping list")
        self.assertIn("2 item(s)", reply)


if __name__ == "__main__":
    unittest.main()
