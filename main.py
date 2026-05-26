# -*- coding: utf-8 -*-
"""
Apex Terminal — Quant Engine v26.2
Fix: Type conversion for Lot data from Sheets
"""

import os
import io
import math
import logging
import sys
import pandas as pd
import yfinance as yf
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ApexTerminal")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1Qr3gmOTXV0dbXolT_ASj1avoBILHUIIiVfqPoSX83M0/export?format=csv"

def get_portfolio():
    try:
        response = requests.get(SHEET_URL)
        df = pd.read_csv(io.StringIO(response.text))
        # Sütun isimlerindeki boşlukları temizle
        df.columns = df.columns.str.strip()
        # Lot sütununu mutlaka tam sayıya çevir (int)
        df['Lot'] = pd.to_numeric(df['Lot']).fillna(0).astype(int)
        return dict(zip(df['Hisse'], df['Lot']))
    except Exception as e:
        log.error(f"Sheets okuma/dönüştürme hatası: {e}")
        return {}

def get_technical(df):
    if df is None or len(df) < 201: return None
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    atr = (high - low).rolling(14).mean()
    vol = close.pct_change().rolling(20).std() * math.sqrt(252)
    last_price = float(close.iloc[-1])
    stop = last_price - (float(atr.iloc[-1]) * 2.5)
    return {"price": last_price, "atr": float(atr.iloc[-1]), "vol": float(vol.iloc[-1]), "stop": round(stop, 2)}

def main():
    portfolio = get_portfolio()
    if not portfolio: 
        log.error("Portföy yüklenemedi!")
        return
    
    raw = yf.download(tickers=list(portfolio.keys()), period="2y", group_by="ticker", progress=False)
    
    analysis = []
    total_value = 0
    
    for s, lot in portfolio.items():
        if s in raw.columns.get_level_values(0):
            tech = get_technical(raw[s].dropna(how="all"))
            if tech:
                val = tech["price"] * lot # Artık lot bir sayı, hata vermez
                analysis.append({"code": s, "lot": lot, "price": tech["price"], "val": val, "stop": tech["stop"], "vol": tech["vol"]})
                total_value += val

    if total_value == 0: return

    md = "# 🏦 Apex Terminal v26.2\n\n| Hisse | Lot | Fiyat | Ağırlık | Stop Loss | V |\n| :--- | ---: | ---: | ---: | ---: | ---: |\n"
    for t in analysis:
        weight = (t["val"] / total_value) * 100
        md += f"| **{t['code']}** | {t['lot']} | {t['price']:.2f} | %{weight:.1f} | {t['stop']:.2f} | {t['vol']:.2f} |\n"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f: f.write(md)
    else: print(md)

if __name__ == "__main__":
    main()
