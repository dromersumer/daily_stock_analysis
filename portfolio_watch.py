# -*- coding: utf-8 -*-
import os
import io
import logging
import pandas as pd
import yfinance as yf
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ApexTerminal")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"

def get_portfolio():
    try:
        response = requests.get(SHEET_URL)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text), decimal=',')
        
        # Başlıkları temizle
        df.columns = df.columns.str.strip().str.lower()
        
        # Dinamik eşleştirme: 'borsa:sembol' artık 'sembol' kelimesiyle yakalanacak
        lot_col = next((col for col in df.columns if 'lot' in col or 'adet' in col), None)
        hisse_col = next((col for col in df.columns if 'hisse' in col or 'ticker' in col or 'sembol' in col), None)
        
        if not lot_col or not hisse_col:
            log.error(f"Sütunlar bulunamadı! Mevcut başlıklar: {list(df.columns)}")
            return {}
            
        df = df.dropna(subset=[hisse_col])
        df[hisse_col] = df[hisse_col].astype(str).str.strip().str.upper()
        df[lot_col] = pd.to_numeric(df[lot_col], errors='coerce').fillna(0.0).astype(float)
        
        return dict(zip(df[hisse_col], df[lot_col]))
    except Exception as e:
        log.error(f"Sheets verisi alınamadı: {e}")
        return {}

# ... (get_technical ve main fonksiyonları aynı kalacak) ...
