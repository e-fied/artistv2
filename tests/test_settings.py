from __future__ import annotations

import json

from app.config import AppSettings, load_settings, save_settings
from app.routes.settings_routes import _parse_model_list


def test_parse_model_list_accepts_commas_and_newlines():
    models = _parse_model_list(
        "gemini-flash-lite-latest,\ngemini-2.5-flash-lite\n gemini-2.5-flash ",
        ["fallback-model"],
    )

    assert models == [
        "gemini-flash-lite-latest",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    ]


def test_save_settings_persists_gemini_controls(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr("app.config.SETTINGS_PATH", settings_path)

    settings = AppSettings(
        public_app_url="https://example.com",
        gemini_extractor_models=["gemini-a", "gemini-b"],
        gemini_extractor_temperature=0.2,
        gemini_autofind_models=["gemini-c"],
        gemini_autofind_temperature=0.1,
        debug_scan_capture=True,
        debug_scan_retention=12,
    )

    save_settings(settings)

    raw = json.loads(settings_path.read_text())
    assert raw["public_app_url"] == "https://example.com"
    assert raw["gemini_extractor_models"] == ["gemini-a", "gemini-b"]
    assert raw["gemini_extractor_temperature"] == 0.2
    assert raw["gemini_autofind_models"] == ["gemini-c"]
    assert raw["gemini_autofind_temperature"] == 0.1
    assert "gemini_api_key" not in raw


def test_load_settings_reads_persisted_gemini_controls(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "public_app_url": "https://example.com",
                "gemini_extractor_models": ["gemini-a", "gemini-b"],
                "gemini_extractor_temperature": 0.3,
                "gemini_autofind_models": ["gemini-c"],
                "gemini_autofind_temperature": 0.4,
            }
        )
    )
    monkeypatch.setattr("app.config.SETTINGS_PATH", settings_path)

    settings = load_settings()

    assert settings.public_app_url == "https://example.com"
    assert settings.gemini_extractor_models == ["gemini-a", "gemini-b"]
    assert settings.gemini_extractor_temperature == 0.3
    assert settings.gemini_autofind_models == ["gemini-c"]
    assert settings.gemini_autofind_temperature == 0.4
