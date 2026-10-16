"""從 `.env` 與環境變數讀取設定。金鑰只從這裡取得，不寫死在程式裡。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """整個工具共用的設定值。"""

    site_url: str = "https://www.sinchih.com.tw"
    crawl_rate_per_sec: float = 1.0
    gsc_site_url: str = "sc-domain:sinchih.com.tw"
    gsc_credentials_file: Path = Path("credentials/service-account.json")
    db_path: Path = Path("seo_radar.db")
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = field(default="", repr=False)
    report_to: tuple[str, ...] = ()


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """讀取 `.env`（若存在）與環境變數，回傳 Settings。

    環境變數優先於 `.env` 檔內容；沒設定的欄位使用預設值。
    傳入 None 表示不讀任何 `.env` 檔，只看環境變數。
    """
    if env_file is not None and Path(env_file).is_file():
        load_dotenv(env_file, override=False)

    defaults = Settings()

    def get(name: str, default: object) -> str:
        """取得環境變數，空字串視為未設定。"""
        value = os.environ.get(name, "").strip()
        return value if value else str(default)

    report_to = tuple(
        addr.strip() for addr in os.environ.get("REPORT_TO", "").split(",") if addr.strip()
    )

    return Settings(
        site_url=get("SITE_URL", defaults.site_url).rstrip("/"),
        crawl_rate_per_sec=float(get("CRAWL_RATE_PER_SEC", defaults.crawl_rate_per_sec)),
        gsc_site_url=get("GSC_SITE_URL", defaults.gsc_site_url),
        gsc_credentials_file=Path(get("GSC_CREDENTIALS_FILE", defaults.gsc_credentials_file)),
        db_path=Path(get("DB_PATH", defaults.db_path)),
        smtp_host=get("SMTP_HOST", defaults.smtp_host),
        smtp_port=int(get("SMTP_PORT", defaults.smtp_port)),
        smtp_user=os.environ.get("SMTP_USER", "").strip(),
        smtp_password=os.environ.get("SMTP_PASSWORD", "").strip(),
        report_to=report_to,
    )
