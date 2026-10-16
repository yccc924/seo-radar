"""pytest 共用設定。"""

import pytest

_ENV_KEYS = (
    "SITE_URL",
    "CRAWL_RATE_PER_SEC",
    "GSC_SITE_URL",
    "GSC_CREDENTIALS_FILE",
    "DB_PATH",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "REPORT_TO",
    "XINCHI_TOOLS_PATH",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每個測試前清掉專案相關環境變數，避免本機 .env 影響測試結果。

    測試結束時 monkeypatch 會把這些變數還原，包含測試中被 load_dotenv 寫入的值。
    """
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
