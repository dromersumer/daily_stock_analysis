# -*- coding: utf-8 -*-
import os
import io
import logging
import pandas as pd
import yfinance as yf
import requests
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ApexTerminal")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"

def get_portfolio():
    try:
        log.info("Sheets verisi çekiliyor...")
        response = requests.get(SHEET_URL)
        response.raise_for_status()
        
        # CSV dosyasını oku
        df = pd.read_csv(io.StringIO(response.text), decimal=',')
        log.info(f"Ham sütun başlıkları: {df.columns.tolist()}")
        
        # Sütunları küçük harfe çevir ve temizle
        df.columns = df.columns.str.strip().str.lower()
        log.info(f"Temizlenmiş sütunlar: {df.columns.tolist()}")
        
        # Sütun eşleştirme mantığı
        lot_col = next((col for col in df.columns if 'lot' in col or 'adet' in col), None)
        hisse_col = next((col for col in df.columns if 'hisse' in col or 'ticker' in col or 'sembol' in col), None)
        
        if not lot_col or not hisse_col:
            log.error(f"EŞLEŞTİRME HATASI! Lütfen Sheets başlıklarını kontrol edin.")
            return {}
            
        log.info(f"Eşleşen sütunlar: Hisse={hisse_col}, Lot={lot_col}")
        
        # Veri temizleme
        df = df.dropna(subset=[hisse_col])
        df[hisse_col] = df[hisse_col].astype(str).str.strip().str.upper()
        df[lot_col] = pd.to_numeric(df[lot_col], errors='coerce').fillna(0.0)
        
        portfolio = dict(zip(df[hisse_col], df[lot_col]))
        log.info(f"Yüklenen portföy: {portfolio}")
        return portfolio
        
    except Exception as e:
        log.error(f"KRİTİK HATA: {e}")
        return {}

def main():
    portfolio = get_portfolio()
    if not portfolio:
        log.error("Portföy yüklenemedi, çıkılıyor.")
        sys.exit(1)
    # ... (geri kalan kod aynı)
