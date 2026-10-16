"""專案骨架與設定讀取的基本測試。"""

from pathlib import Path

import pytest

import seo_radar
from seo_radar.config import Settings, load_settings

ROOT = Path(__file__).resolve().parent.parent


def test_package_importable() -> None:
    """套件可以被匯入並有版本號。"""
    assert seo_radar.__version__


def test_defaults_without_env() -> None:
    """沒有 .env 也沒有環境變數時使用預設值。"""
    settings = load_settings(None)
    assert settings == Settings()
    assert settings.crawl_rate_per_sec == 1.0


def test_load_from_env_file(tmp_path: Path) -> None:
    """可以從指定的 .env 檔讀到設定。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SITE_URL=https://example.com/\n"
        "SMTP_PORT=465\n"
        "SMTP_PASSWORD=secret\n"
        "REPORT_TO=a@example.com, b@example.com\n",
        encoding="utf-8",
    )
    settings = load_settings(env_file)
    assert settings.site_url == "https://example.com"
    assert settings.smtp_port == 465
    assert settings.smtp_password == "secret"
    assert settings.report_to == ("a@example.com", "b@example.com")


def test_env_var_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """環境變數優先於 .env 檔。"""
    env_file = tmp_path / ".env"
    env_file.write_text("DB_PATH=from_file.db\n", encoding="utf-8")
    monkeypatch.setenv("DB_PATH", "from_env.db")
    assert load_settings(env_file).db_path == Path("from_env.db")


def test_password_not_in_repr() -> None:
    """密碼不會出現在 repr，避免被印進 log。"""
    assert "hunter2" not in repr(Settings(smtp_password="hunter2"))


def test_env_example_covers_settings() -> None:
    """.env.example 列出所有設定欄位，且沒有填入真正的密碼。"""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    keys = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    expected = {name.upper() for name in Settings.__dataclass_fields__}
    assert expected <= keys
    assert "SMTP_PASSWORD=\n" in text


def test_gitignore_protects_secrets() -> None:
    """.gitignore 擋住 .env 與 credentials/。"""
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines
    assert "credentials/" in lines
