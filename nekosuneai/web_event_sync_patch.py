from __future__ import annotations

"""Keep browser dashboard events available to every connected client.

The original web event queue was destructive: the first browser calling
/api/events emptied the queue. That meant a domain dashboard, mobile browser,
or second tab could steal chat/state events from every other client. This patch
turns it into a bounded replay buffer with monotonically increasing event IDs.
"""

_INSTALLED = False


def install_web_event_sync_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from .webgui import Api

    if getattr(Api, "_neko_multi_client_events", False):
        return

    def _queue_web_event(self, event):
        with self._web_events_lock:
            seq = int(getattr(self, "_web_event_seq", 0)) + 1
            self._web_event_seq = seq
            item = dict(event or {})
            item["event_id"] = seq
            self._web_events.append(item)
            if len(self._web_events) > 500:
                del self._web_events[:-500]

    def get_web_events(self):
        # Non-destructive replay buffer. Browser clients track event_id locally,
        # so multiple tabs/devices can receive the same chat/state updates.
        with self._web_events_lock:
            return [dict(item) for item in self._web_events]

    def get_web_event_cursor(self):
        with self._web_events_lock:
            return int(getattr(self, "_web_event_seq", 0))

    Api._queue_web_event = _queue_web_event
    Api.get_web_events = get_web_events
    Api.get_web_event_cursor = get_web_event_cursor
    Api._neko_multi_client_events = True
