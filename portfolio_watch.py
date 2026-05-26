# -*- coding: utf-8 -*-
import os
import io
import logging
import pandas as pd
import yfinance as yf
import requests
import sys

# Log seviyesini DEBUG yapıyoruz ki her adımı görelim
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ApexTerminal")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"

def get_portfolio():
    try:
        log.debug("Sheets URL'sine istek gönderiliyor...")
        response = requests.get(SHEET_URL)
        response.raise_for_status()
        
        # İçeriği oku
        df = pd.read_csv(io.StringIO(response.text), decimal=',')
        log.debug(f"DataFrame sütunları: {df.columns.tolist()}")
        
        df.columns = df.columns.str.strip().str.lower()
        
        lot_col = next((col for col in df.columns if 'lot' in col or 'adet' in col), None)
        hisse_col = next((col for col in df.columns if 'hisse' in col or 'ticker' in col or 'sembol' in col), None)
        
        log.debug(f"Tespit edilen: Hisse={hisse_col}, Lot={lot_col}")
        
        if not lot_col or not hisse_col:
            log.error("Sütunlar eşleştirilemedi!")
            return {}
            
        # Veri temizleme
        df = df.dropna(subset=[hisse_col])
        df[hisse_col] = df[hisse_col].astype(str).str.strip().str.upper()
        df = df[~df[hisse_col].isin(['0', '0.0', 'NAN', ''])]
        df[lot_col] = pd.to_numeric(df[lot_col], errors='coerce').fillna(0.0)
        
        portfolio = dict(zip(df[hisse_col], df[lot_col]))
        log.info(f"Portföy başarıyla oluşturuldu: {len(portfolio)} kalem.")
        return portfolio
        
    except Exception as e:
        log.error(f"HATA: {e}", exc_info=True)
        return {}

def main():
    log.info("--- Apex Terminal Başlıyor ---")
    portfolio = get_portfolio()
    
    if not portfolio:
        log.error("Portföy boş! İşlem durduruluyor.")
        sys.exit(1)
        
    log.info(f"İndirilecek hisseler: {list(portfolio.keys())}")
    
    raw = yf.download(list(portfolio.keys()), period="2y", group_by='ticker', auto_adjust=True, progress=False)
    
    md = "# 🏦 Apex Terminal Raporu\n\n| Hisse | Lot | Durum |\n| :--- | ---: | :--- |\n"
    for s, lot in portfolio.items():
        data = raw[s].dropna() if s in raw.columns.get_level_values(0) else None
        if data is not None and not data.empty:
            md += f"| **{s}** | {lot:.2f} | Veri Alındı |\n"
        else:
            md += f"| **{s}** | {lot:.2f} | ❌ Hata (Veri Yok) |\n"
            log.warning(f"Hisse verisi alınamadı: {s}")

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f: f.write(md)
    log.info("İşlem tamamlandı.")

if __name__ == "__main__":
    main()
