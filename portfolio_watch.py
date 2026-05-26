# -*- coding: utf-8 -*-
"""
Apex Terminal — Portfolio Watch v27.1
Ref: Optimized for new Google Sheets (1_bi1N5770...)
"""

import os
import io
import logging
import pandas as pd
import yfinance as yf
import requests

# Günlük log kaydı
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ApexTerminal")

# Sizin yeni Google Sheets dosya URL'niz
SHEET_URL = "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"

def get_portfolio():
    try:
        response = requests.get(SHEET_URL)
        response.raise_for_status()
        
        # 'decimal=','' ile Türkçedeki virgüllü sayıları otomatik noktalı hale getirir
        df = pd.read_csv(io.StringIO(response.text), decimal=',')
        
        df.columns = df.columns.str.strip().str.lower()
        
        # Sütunları dinamik bulma
        lot_col = next((col for col in df.columns if 'lot' in col or 'adet' in col), None)
        hisse_col = next((col for col in df.columns if 'hisse' in col or 'ticker' in col), None)
        
        if not lot_col or not hisse_col:
            log.error(f"Sütunlar bulunamadı! Mevcut başlıklar: {list(df.columns)}")
            return {}
            
        # Veri temizleme
        df = df.dropna(subset=[hisse_col])
        df[hisse_col] = df[hisse_col].astype(str).str.strip().str.upper()
        df = df[~df[hisse_col].isin(['0', '0.0', 'NAN', ''])]
        df[lot_col] = pd.to_numeric(df[lot_col], errors='coerce').fillna(0.0).astype(float)
        
        return dict(zip(df[hisse_col], df[lot_col]))
    except Exception as e:
        log.error(f"Sheets verisi alınamadı: {e}")
        return {}

def get_technical(data):
    if data is None or len(data) < 20: return None
    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    
    # Wilder's True Range (ATR)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean().iloc[-1]
    
    last_price = float(close.iloc[-1])
    vol = close.pct_change().rolling(20).std() * (252**0.5)
    
    return {"price": last_price, "stop": round(last_price - (atr * 2.5), 2), "vol": float(vol.iloc[-1])}

def main():
    portfolio = get_portfolio()
    if not portfolio: return
    
    # Çoklu veri çekme (auto_adjust=True ile bölünmeleri temizler)
    raw = yf.download(list(portfolio.keys()), period="2y", group_by='ticker', auto_adjust=True, progress=False)
    
    md = "# 🏦 Apex Terminal v27.1\n\n| Hisse | Lot | Fiyat | Stop Loss | V |\n| :--- | ---: | ---: | ---: | ---: |\n"
    for s, lot in portfolio.items():
        # Veriyi temizle (MultiIndex veya tekli durumu yönet)
        data = raw[s].dropna() if s in raw.columns.get_level_values(0) else None
        if data is not None and not data.empty:
            tech = get_technical(data)
            md += f"| **{s}** | {lot:.2f} | {tech['price']:.2f} | {tech['stop']:.2f} | {tech['vol']:.2f} |\n"

    # GitHub Summary dosyasını temiz bir şekilde yaz
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f: f.write(md)
    else: print(md)

if __name__ == "__main__":
    main()
