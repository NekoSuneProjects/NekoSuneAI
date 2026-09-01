from nekosuneai.twitch_chat import TwitchChatManager


def test_prioritises_mentions_questions_and_rate_limits():
    calls = []
    manager = TwitchChatManager(
        lambda user, text: calls.append((user, text)) or "Thanks for asking!",
        now_fn=lambda: 100,
    )
    replies = manager.ingest([
        {"id": "1", "user": "Quiet", "text": "hello everyone"},
        {"id": "2", "user": "Viewer", "text": "NekoSuneAI, how are you?"},
        {"id": "3", "user": "Viewer", "text": "Another question?"},
    ])
    assert replies == [{"reply_to": "Viewer", "text": "@Viewer Thanks for asking!"}]
    assert calls == [("Viewer", "NekoSuneAI, how are you?")]
    assert manager.ingest([{"id": "2", "user": "Viewer", "text": "duplicate"}]) == []


def test_viewer_commands_are_allowlisted_and_never_become_pc_actions():
    manager = TwitchChatManager(lambda *_: "unused", now_fn=lambda: 100)
    replies = manager.ingest([
        {"id": "1", "user": "GoodViewer", "text": "!hello"},
        {"id": "2", "user": "BadViewer", "text": "!startstream"},
        {"id": "3", "user": "BadViewer", "text": "!presskey w"},
    ])
    assert replies == [{"reply_to": "GoodViewer", "text": "@GoodViewer hello!"}]
    assert all(set(row) == {"reply_to", "text"} for row in replies)


def test_repetition_flood_is_deduplicated():
    manager = TwitchChatManager(lambda *_: "answer", cooldown_seconds=3, now_fn=lambda: 100)
    replies = manager.ingest([
        {"id": str(i), "user": f"viewer{i}", "text": "NekoSuneAI same message?"}
        for i in range(20)
    ])
    assert len(replies) == 1
