# -*- coding: utf-8 -*-
import os
import io
import logging
import pandas as pd
import yfinance as yf
import requests
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ApexTerminal")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"


def get_portfolio() -> dict:
    try:
        response = requests.get(SHEET_URL, timeout=15)
        response.raise_for_status()

        df = pd.read_csv(io.StringIO(response.content.decode('utf-8-sig')))
        df.columns = df.columns.str.strip().str.lower()

        hisse_col = 'hisse'
        lot_col = 'lot'

        if hisse_col not in df.columns or lot_col not in df.columns:
            log.error(f"HATA: 'Hisse' veya 'Lot' sütunu bulunamadı! Bulunanlar: {df.columns.tolist()}")
            return {}

        df = df.dropna(subset=[hisse_col])
        df[hisse_col] = df[hisse_col].astype(str).str.strip().str.upper()
        # Exchange prefix temizle: "NASDAQ:VOO" → "VOO"
        df[hisse_col] = df[hisse_col].str.split(":").str[-1]
        # Türkçe locale lot parse: "0,30" → 0.30
        df[lot_col] = (
            df[lot_col].astype(str)
            .str.replace(",", ".", regex=False)
            .pipe(pd.to_numeric, errors="coerce")
            .fillna(0)
        )
        df = df[df[lot_col] > 0]

        portfolio = dict(zip(df[hisse_col], df[lot_col]))
        log.info(f"Portföy yüklendi: {len(portfolio)} kalem → {list(portfolio.keys())}")
        return portfolio

    except Exception as e:
        log.error(f"KRİTİK HATA: {e}", exc_info=True)
        return {}


def get_close_price(raw: pd.DataFrame, ticker: str) -> float | None:
    """Yeni yfinance formatında (field → ticker) kapanış fiyatını çeker."""
    try:
        # Yeni format: raw["Close"]["VOO"]
        if isinstance(raw.columns, pd.MultiIndex):
            return raw["Close"][ticker].dropna().iloc[-1]
        else:
            # Tek ticker, düz DataFrame
            return raw["Close"].dropna().iloc[-1]
    except Exception:
        return None


def main():
    portfolio = get_portfolio()
    if not portfolio:
        log.error("Portföy boş döndü.")
        sys.exit(1)

    tickers = list(portfolio.keys())
    log.info(f"İndirilecek {len(tickers)} hisse: {tickers}")

    raw = yf.download(tickers, period="1mo", auto_adjust=True, progress=False)

    # Tek ticker edge case: düz DataFrame'i MultiIndex'e çevir
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw = pd.concat({tickers[0]: raw}, axis=1).swaplevel(axis=1)
        # Sonuç: raw["Close"]["VOO"] formatına uygun

    log.info(f"Ham veri sütunları: {raw.columns.tolist()[:6]}...")

    # Önce tüm fiyatları çek, toplam portföy değerini hesapla
    prices = {s: get_close_price(raw, s) for s in tickers}
    total_value = sum(
        portfolio[s] * prices[s]
        for s in tickers
        if prices[s] is not None
    )

    md = "# 🏦 Portföy Raporu\n\n| Hisse | Lot | Son Fiyat | Değer (USD) | Ağırlık % |\n| :--- | ---: | ---: | ---: | ---: |\n"
    for s in tickers:
        price = prices[s]
        if price is not None:
            value = portfolio[s] * price
            weight = (value / total_value * 100) if total_value > 0 else 0.0
            price_str = f"${price:.2f}"
            value_str = f"${value:,.2f}"
            weight_str = f"%{weight:.1f}"
        else:
            price_str = value_str = weight_str = "❌"
            log.warning(f"Fiyat alınamadı: {s}")
        md += f"| {s} | {portfolio[s]:.2f} | {price_str} | {value_str} | {weight_str} |\n"

    # Toplam satırı
    md += f"| **TOPLAM** | — | — | **${total_value:,.2f}** | **%100.0** |\n"

    # Fiyatı çekilemeyen varlıklar uyarısı
    missing = [s for s in tickers if prices[s] is None]
    if missing:
        md += f"\n> ⚠️ **Uyarı:** Fiyatı çekilemeyen varlıklar (delist/ticker değişimi olabilir): `{'`, `'.join(missing)}`\n"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)
    log.info("İşlem tamamlandı.")


if __name__ == "__main__":
    main()
