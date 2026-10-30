from src.settings import Settings


def test_only_credentials_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("SETTINGS_MODEL", "test-model")
    monkeypatch.setenv("SETTINGS_MAX_STEPS", "invalid")
    settings = Settings(_env_file=None)
    assert settings.model == "test-model"
    assert settings.max_steps == 20
    assert Settings(max_steps=3, _env_file=None).max_steps == 3
