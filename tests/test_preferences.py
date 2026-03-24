from prompt_optimizer import preferences


def test_preferences_round_trip(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(preferences, "PREFERENCES_PATH", state_file)

    preferences.save_preferences(
        last_project_path=r"D:\projects\demo",
        last_remote_git_url="https://github.com/example/repo",
    )

    payload = preferences.load_preferences()
    assert payload["last_project_path"] == r"D:\projects\demo"
    assert payload["last_remote_git_url"] == "https://github.com/example/repo"


def test_preferences_handles_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(preferences, "PREFERENCES_PATH", tmp_path / "missing.json")
    assert preferences.load_preferences() == {}


def test_default_preferences_path_uses_env_override(tmp_path, monkeypatch):
    override = tmp_path / "custom-state.json"
    monkeypatch.setenv(preferences.PREFERENCES_ENV_VAR, str(override))

    assert preferences._default_preferences_path() == override
