# -*- coding: utf-8 -*-
import os, json, math
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np

# Google GenAI Modülü
try:
    from google import genai as google_genai
except ImportError:
    google_genai = None

# --- PORTFÖY VE AYARLAR ---
PORTFOLIO_TYPE = os.getenv("PORTFOLIO_TYPE", "BIST").upper()
START_CAPITAL = float(os.getenv("PORTFOLIO_CAPITAL", "10000" if PORTFOLIO_TYPE == "ABD" else "100000"))
MAX_PORTFOLIO_SIZE = 19
MAX_WEIGHT_PER_STOCK = 0.35
USE_AI = os.getenv("USE_AI", "false").lower() == "true"
CURRENCY = "$" if PORTFOLIO_TYPE == "ABD" else "₺"

# (Mevcut CURRENT_PORTFOLIO yapısı aynı kalmalı...)

def get_technical(df):
    close = df['Close']
    df['ema200'] = close.ewm(span=200).mean()
    tr = pd.concat([df['High'] - df['Low'], (df['High'] - close.shift()).abs(), (df['Low'] - close.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean().dropna()
    df['vol'] = close.pct_change().rolling(20).std() * np.sqrt(252)
    last = df.iloc[-1]
    regime = "TREND" if last['Close'] > last['ema200'] else "WEAK"
    return {"price": round(float(last['Close']), 2), "atr": round(float(last['atr']), 2), "vol": float(last['vol']), "regime": regime}

# get_ai_comments fonksiyonu aynı kalabilir...

def main():
    stock_input = os.getenv("STOCK_LIST", "VOO,SCHD,QQQM,SPUS,VXUS,O,WPC,SMH,AIS,NASA,EUV,CHAT,NVDA,AVGO,GOOG,CAT,LENZ,ASPI")
    stocks = [s.strip().upper() for s in stock_input.split(",") if s.strip()]
    data = yf.download(tickers=" ".join(stocks), period="2y", group_by="ticker")
    if data is None or data.empty: return

    techs, scores = {}, {}
    for s in stocks:
        if s not in data.columns.get_level_values(0): continue
        df = data[s].dropna()
        if len(df) < 200: continue
        t = get_technical(df)
        techs[s] = t
        scores[s] = (40 if t['regime'] == "TREND" else 0) + (max(1 - t['vol'], 0) * 30)
    
    selected = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]
    weights = {s: 1/len(selected) for s in selected}
    
    available_cash = 0 # Örnek değer
    effective_capital = START_CAPITAL + available_cash
    target = []
    for s in selected:
        price = techs[s]['price']
        vol = techs[s]['vol']
        # Stop-loss hesaplama: Volatilite arttıkça stop alanı genişler
        stop_val = round(price - (techs[s]['atr'] * (2.0 + (vol * 2.0))), 2)
        target.append({"code": s, "lot": math.floor((effective_capital * weights[s]) / price), "price": price, "stop": stop_val, "vol": vol})

    # RAPORLAMA KATMANI
    md = f"## 🏦 Apex Terminal v25.3 ({PORTFOLIO_TYPE})\n"
    md += """
### 📝 Terimler Sözlüğü
* **V (Volatilite):** Hissenin yıllıklandırılmış fiyat oynaklığı. Yüksek V değeri, hissenin sert hareketler yapma potansiyelini (riski) gösterir.
* **Dinamik Stop:** Hissenin ATR değeri ile V değerinin çarpımıyla oluşur. V arttıkça stop mesafesi otomatik genişler.
* **TREND:** Fiyatın 200 günlük hareketli ortalamanın üzerinde olduğu yükseliş evresi.
"""
    md += "\n| İşlem | Hisse | Analiz |\n| :--- | :--- | :--- |\n"
    # ... (orders ve rapor döngüleri aynı kalacak)
    md += "\n### 🎯 HEDEF PORTFÖY VE DİNAMİK STOP\n| Hisse | Lot | Fiyat | V | Stop |\n| :--- | :--- | :--- | :--- | :--- |\n"
    for t in target:
        md += f"| **{t['code']}** | {t['lot']} | {t['price']} | {t['vol']:.2f} | {t['stop']} |\n"
    
    # ... (Summary yazma kısmı)
