import json

import pytest

from nekosuneai.game_skills import GameSkillLibrary, SkillLearningStore


def test_bundled_game_skill_packages_are_valid_and_independent():
    library = GameSkillLibrary("game-skills")
    packages = {row["game_id"]: row for row in library.discover()}
    assert {"minecraft", "terraria", "cyberpunk2077", "no-mans-sky", "skyrim"} <= packages.keys()
    assert {"xbox-remote-play", "playstation-remote-play"} <= packages.keys()
    minecraft = library.load("minecraft")
    assert "minecraft.walk_forward" in minecraft.skills
    assert minecraft.skill_metadata["minecraft.walk_forward"]["realtime"] is True
    assert "private server" in minecraft.guide.lower()


def test_library_rejects_code_or_path_traversal_packages(tmp_path):
    library = GameSkillLibrary(tmp_path)
    with pytest.raises(ValueError, match="invalid game package id"):
        library.load("../private")
    folder = tmp_path / "bad-game"
    folder.mkdir()
    (folder / "game.json").write_text(json.dumps({
        "schema_version": 1, "game_id": "bad-game", "display_name": "Bad",
        "profile": {"multiplayer_policy": "single_player"},
        "skills": {"shell.run": {"steps": [{"script": "calc.exe"}]}},
    }), "utf-8")
    with pytest.raises(ValueError, match="approved input"):
        library.load("bad-game")


def test_learning_store_aggregates_results_without_frames_or_inputs(tmp_path):
    path = tmp_path / "minecraft-learning.json"
    learning = SkillLearningStore(path, "minecraft")
    learning.record("minecraft.jump", True, 20)
    learning.record("minecraft.jump", False, 40, "blocked path")
    row = learning.snapshot()["minecraft.jump"]
    assert row["attempts"] == 2
    assert row["reliability"] == 0.5
    assert row["last_reason"] == "blocked path"
    persisted = path.read_text("utf-8")
    assert "screenshot" not in persisted and "keypress" not in persisted
    assert SkillLearningStore(path, "minecraft").snapshot()["minecraft.jump"]["attempts"] == 2
