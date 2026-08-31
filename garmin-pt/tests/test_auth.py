import pytest

from garmin_pt.garmin import auth
from garmin_pt.garmin.client import AuthError


def test_prompt_mfa_totp_generates_code():
    prompt = auth.build_prompt_mfa("JBSWY3DPEHPK3PXP", interactive=False)
    code = prompt()
    assert code.isdigit() and len(code) == 6


def test_prompt_mfa_noninteractive_without_secret_refuses():
    prompt = auth.build_prompt_mfa(None, interactive=False)
    with pytest.raises(AuthError, match="garmin-pt auth"):
        prompt()


def test_token_status_missing(settings):
    st = auth.token_status(settings)
    assert st["present"] is False


def test_token_status_present(settings):
    settings.tokens_dir.mkdir(parents=True)
    (settings.tokens_dir / "garmin_tokens.json").write_text("{}")
    st = auth.token_status(settings)
    assert st["present"] is True
    assert st["files"] == ["garmin_tokens.json"]
