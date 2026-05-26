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

def get_portfolio():
    try:
        response = requests.get(SHEET_URL)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.content.decode('utf-8-sig')))
        df.columns = df.columns.str.strip().str.lower()
        
        hisse_col, lot_col = 'hisse', 'lot'
        
        if hisse_col not in df.columns or lot_col not in df.columns:
            return {}

        df = df.dropna(subset=[hisse_col])
        df[hisse_col] = df[hisse_col].astype(str).str.strip().str.upper().str.split(":").str[-1]
        df[lot_col] = df[lot_col].astype(str).str.replace(",", ".", regex=False).pipe(pd.to_numeric, errors="coerce").fillna(0)
        df = df[df[lot_col] > 0]
        
        return dict(zip(df[hisse_col], df[lot_col]))
    except Exception as e:
        log.error(f"KRİTİK HATA: {e}")
        return {}

def main():
    portfolio = get_portfolio()
    if not portfolio: sys.exit(1)
        
    tickers = list(portfolio.keys())
    raw = yf.download(tickers, period="1mo", auto_adjust=True, progress=False)
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw.columns = pd.MultiIndex.from_product([raw.columns, tickers])

    # Fiyatları al ve Toplam Değeri hesapla
    total_value = 0
    data_map = {}
    
    for s in tickers:
        try:
            close = raw[s]["Close"].dropna().iloc[-1]
            val = close * portfolio[s]
            data_map[s] = {"price": close, "val": val}
            total_value += val
        except:
            data_map[s] = {"price": 0, "val": 0}

    # Raporu oluştur
    md = "# 🏦 Portföy Raporu\n\n| Hisse | Lot | Fiyat | Ağırlık (%) |\n| :--- | ---: | ---: | ---: |\n"
    for s in tickers:
        price = data_map[s]["price"]
        weight = (data_map[s]["val"] / total_value * 100) if total_value > 0 else 0
        md += f"| {s} | {portfolio[s]:.2f} | ${price:.2f} | %{weight:.2f} |\n"
        
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f: f.write(md)
    print(md)

if __name__ == "__main__":
    main()
