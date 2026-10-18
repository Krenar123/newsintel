from types import SimpleNamespace

from src.api.main import (
    _clear_login_failures,
    _login_attempt_key,
    _login_retry_after,
    _record_login_failure,
)


def test_login_attempt_key_separates_email_and_ip():
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    assert _login_attempt_key(request, " USER@example.com ") == (
        "127.0.0.1:user@example.com"
    )


def test_failed_login_is_temporarily_throttled(monkeypatch):
    key = "test-ip:test-rate-limit@example.com"
    monkeypatch.setattr("src.api.main.settings.login_max_attempts", 2)
    monkeypatch.setattr("src.api.main.settings.login_window_minutes", 15)
    _clear_login_failures(key)

    _record_login_failure(key)
    assert _login_retry_after(key) == 0
    _record_login_failure(key)
    assert _login_retry_after(key) > 0

    _clear_login_failures(key)
    assert _login_retry_after(key) == 0
