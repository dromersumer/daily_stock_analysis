Hisse	Lot
VOO	0.30
SCHD	8.00

bu şekilde ABDPortfoy.csv dosyasını değiştirdim.

portfolio_watch.py dosyasını da şu şekilde yaptım:
# -*- coding: utf-8 -*-
import os
import io
import logging
import pandas as pd
import yfinance as yf
import requests
import sys

# Loglama seviyesini sadeleştirdik
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ApexTerminal")

# Sheets URL
SHEET_URL = "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"

def get_portfolio():
    try:
        response = requests.get(SHEET_URL)
        response.raise_for_status()
        
        # Dosyayı oku ve UTF-8 BOM karakterlerinden temizle
        df = pd.read_csv(io.StringIO(response.content.decode('utf-8-sig')))
        
        # Sütun isimlerini tam olarak sizin istediğiniz gibi eşleştiriyoruz
        # Küçük harfe çevirip boşlukları alıyoruz
        df.columns = df.columns.str.strip().str.lower()
        
        # SADECE 'hisse' ve 'lot' arıyoruz
        hisse_col = 'hisse'
        lot_col = 'lot'
        
        if hisse_col not in df.columns or lot_col not in df.columns:
            log.error(f"HATA: Sheets dosyasında 'Hisse' veya 'Lot' sütunu bulunamadı!")
            log.error(f"Bulunan sütunlar: {df.columns.tolist()}")
            return {}

        # Temizlik
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
        
        return dict(zip(df[hisse_col], df[lot_col]))
        
    except Exception as e:
        log.error(f"KRİTİK HATA: {e}")
        return {}

def main():
    portfolio = get_portfolio()
    if not portfolio:
        log.error("Portföy boş döndü.")
        sys.exit(1)
        
    # Veri indirme
    tickers = list(portfolio.keys())
    raw = yf.download(tickers, period="1mo", auto_adjust=True, progress=False)

    # Tek ticker edge case: MultiIndex'e normalize et
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw.columns = pd.MultiIndex.from_product([raw.columns, tickers])

    # Rapor
    md = "# 🏦 Portföy Raporu\n\n| Hisse | Lot | Son Fiyat |\n| :--- | ---: | ---: |\n"
    for s in tickers:
        try:
            close = raw[s]["Close"].dropna().iloc[-1]
            price_str = f"${close:.2f}"
        except Exception:
            price_str = "—"
            log.warning("Fiyat alınamadı: %s", s)
        md += f"| {s} | {portfolio[s]:.2f} | {price_str} |\n"
        
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)

if __name__ == "__main__":
    main()
