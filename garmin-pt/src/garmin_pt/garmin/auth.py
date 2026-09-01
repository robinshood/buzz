"""Innlogging og token-livssyklus.

Tokens lagres i settings.tokens_dir — garminconnect==0.3.11 skriver selv
0600-fil i 0700-katalog og auto-refresher DI-tokens før hvert kall, så daglig
cron trenger bare token-filen. E-post/passord fra .env brukes først når
tokenene er helt utløpt; MFA løses med TOTP-secret (pyotp) eller interaktiv
prompt.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from ..config import Settings
from .client import AuthError, GarminClient


def build_prompt_mfa(totp_secret: str | None, *, interactive: bool) -> Callable[[], str]:
    if totp_secret:

        def from_totp() -> str:
            try:
                import pyotp
            except ImportError as e:
                raise AuthError(
                    "GARMIN_TOTP_SECRET er satt, men pyotp mangler — "
                    "installer med: uv sync --extra totp"
                ) from e
            return pyotp.TOTP(totp_secret).now()

        return from_totp

    if interactive:
        return lambda: input("MFA-kode fra Garmin (SMS/e-post/app): ").strip()

    def refuse() -> str:
        raise AuthError(
            "Garmin krever MFA, men kjøringen er ikke interaktiv og "
            "GARMIN_TOTP_SECRET er ikke satt. Kjør 'garmin-pt auth' manuelt."
        )

    return refuse


def login(settings: Settings, *, interactive: bool = True) -> GarminClient:
    """Logg inn (resume fra tokens når mulig) og returner wrappet klient."""
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
    )

    email = os.environ.get("GARMIN_EMAIL") or None
    password = os.environ.get("GARMIN_PASSWORD") or None
    totp = os.environ.get("GARMIN_TOTP_SECRET") or None

    settings.tokens_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(settings.tokens_dir, 0o700)

    api = Garmin(
        email=email,
        password=password,
        prompt_mfa=build_prompt_mfa(totp, interactive=interactive),
    )
    try:
        api.login(tokenstore=str(settings.tokens_dir))
    except GarminConnectAuthenticationError as e:
        raise AuthError(
            f"Garmin-innlogging avvist: {e}. Sjekk GARMIN_EMAIL/GARMIN_PASSWORD "
            "i .env, eller kjør 'garmin-pt auth' interaktivt for MFA."
        ) from e
    except GarminConnectConnectionError as e:
        raise AuthError(f"Fikk ikke kontakt med Garmin SSO: {e}") from e
    return GarminClient(api)


def token_status(settings: Settings) -> dict:
    """Ingen nettverk: finnes det token-filer, og når ble de sist fornyet?"""
    if not settings.tokens_dir.exists():
        return {"present": False, "hint": "kjør 'garmin-pt auth'"}
    files = sorted(settings.tokens_dir.glob("*.json"))
    if not files:
        return {"present": False, "hint": "kjør 'garmin-pt auth'"}
    newest = max(f.stat().st_mtime for f in files)
    return {"present": True, "files": [f.name for f in files], "mtime": newest}
