# -*- coding: utf-8 -*-
"""
Apex Terminal — Quant Engine v26.0
Architecture: Dynamic Portfolio Sync (via Google Sheets)
"""

import os
import io
import math
import logging
import sys
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timezone

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ApexTerminal")

# ── Konfigürasyon ──────────────────────────────────────────────────────────
START_CAPITAL = float(os.getenv("PORTFOLIO_CAPITAL", "10000"))
MAX_PORTFOLIO_SIZE = int(os.getenv("MAX_PORTFOLIO_SIZE", "19"))
SHEET_URL = "https://docs.google.com/spreadsheets/d/1Qr3gmOTXV0dbXolT_ASj1avoBILHUIIiVfqPoSX83M0/export?format=csv"

def get_portfolio_from_sheets():
    try:
        response = requests.get(SHEET_URL)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        # Hisse ve Lot sütunlarını sözlüğe çevir
        return dict(zip(df['Hisse'], df['Lot']))
    except Exception as e:
        log.error(f"Sheets okuma hatası: {e}")
        return {}

# ── Analiz Fonksiyonları ────────────────────────────────────────────────────
def get_technical(df: pd.DataFrame):
    if df is None or len(df) < 201: return None
    close = df["Close"].astype(float)
    vol = close.pct_change().rolling(20).std() * math.sqrt(252)
    ema200 = close.ewm(span=200, adjust=False).mean()
    atr = (df["High"] - df["Low"]).rolling(14).mean()
    return {
        "price": float(close.iloc[-1]),
        "vol": float(vol.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "regime": "TREND" if close.iloc[-1] > ema200.iloc[-1] else "WEAK"
    }

# ── Ana Motor ──────────────────────────────────────────────────────────────
def main():
    # 1. Portföyü Sheets'ten çek
    portfolio = get_portfolio_from_sheets()
    stocks = list(portfolio.keys())
    
    log.info(f"Portföy senkronize edildi: {stocks}")

    # 2. Veri Çek ve Analiz Et
    raw = yf.download(tickers=stocks, period="2y", group_by="ticker", progress=False)
    
    target_data = []
    for s in stocks:
        if s in raw.columns.get_level_values(0):
            tech = get_technical(raw[s].dropna(how="all"))
            if tech:
                target_data.append({
                    "code": s, 
                    "lot": portfolio[s], 
                    "price": tech["price"],
                    "vol": tech["vol"]
                })

    # 3. Rapor Oluşturma
    md = "# 🏦 Apex Terminal v26.0 (Live Sync)\n\n### 🎯 MEVCUT PORTFÖY DURUMU\n| Hisse | Mevcut Lot | Fiyat | Oynaklık (V) |\n| :--- | ---: | ---: | ---: |\n"
    for t in target_data:
        md += f"| **{t['code']}** | {t['lot']} | {t['price']:.2f} | {t['vol']:.2f} |\n"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f: f.write(md)
    else: print(md)

if __name__ == "__main__":
    main()
