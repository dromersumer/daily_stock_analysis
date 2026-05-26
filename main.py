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

# --- 1. PORTFÖY TİPİ VE DİNAMİK DEĞİŞKENLER ---
PORTFOLIO_TYPE = os.getenv("PORTFOLIO_TYPE", "BIST").upper()
default_capital = "10000" if PORTFOLIO_TYPE == "ABD" else "100000"
START_CAPITAL = float(os.getenv("PORTFOLIO_CAPITAL", default_capital))

MAX_PORTFOLIO_SIZE = 19
MAX_WEIGHT_PER_STOCK = 0.35
LOOKBACK_DAYS = 252
USE_AI = os.getenv("USE_AI", "false").lower() == "true"
CURRENCY = "$" if PORTFOLIO_TYPE == "ABD" else "₺"

# --- GÜNCEL PORTFÖYLER ---
if PORTFOLIO_TYPE == "ABD":
    CURRENT_PORTFOLIO = {
        "VOO": 0, "SCHD": 8, "QQQM": 3, "SPUS": 9, "VXUS": 0, "O": 0, "WPC": 0,
        "SMH": 0.257, "AIS": 0, "NASA": 2, "EUV": 0, "CHAT": 1, "NVDA": 3.539,
        "AVGO": 1.526, "GOOG": 1.0063, "CAT": 0.1, "LENZ": 0, "ASPI": 0, "CASH": 0
    }
else:
    CURRENT_PORTFOLIO = {
        "AKSEN.IS": 10, "ALTNY.IS": 67.5, "ASELS.IS": 71, "ASTOR.IS": 30,
        "BIMAS.IS": 5, "EREGL.IS": 135, "FROTO.IS": 10, "ISDMR.IS": 82,
        "ISMEN.IS": 13, "KATMR.IS": 1000, "KCHOL.IS": 6, "KONTR.IS": 115,
        "MIATK.IS": 27, "ODINE.IS": 1, "OTKAR.IS": 3, "RALYH.IS": 12.28,
        "SISE.IS": 36, "THYAO.IS": 2, "TUPRS.IS": 10, "CASH": 100000
    }

def safe_round(x, n=2):
    try: return round(float(x), n) if pd.notna(x) else 0
    except: return 0

def get_technical(df):
    close = df['Close']
    df['ema200'] = close.ewm(span=200).mean()
    tr = pd.concat([df['High'] - df['Low'], (df['High'] - close.shift()).abs(), (df['Low'] - close.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean().dropna()
    df['vol'] = close.pct_change().rolling(20).std() * np.sqrt(LOOKBACK_DAYS)
    last = df.iloc[-1]
    regime = "TREND" if last['Close'] > last['ema200'] and safe_round(close.pct_change(20).iloc[-1], 4) > 0 else "WEAK"
    return {"price": safe_round(last['Close']), "atr": safe_round(last['atr']), "vol": float(last['vol']), "regime": regime}

def get_ai_comments(orders, techs):
    comments = {}
    client = None
    if USE_AI and google_genai is not None:
        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key: client = google_genai.Client(api_key=api_key)
        except: pass

    for o in orders:
        code = o['code']
        t = techs.get(code, {})
        if client and t:
            try:
                res = client.models.generate_content(model="gemini-1.5-flash", contents=f"'{code}' teknik: Fiyat {t.get('price')}, {t.get('regime')}. Max 10 kelime yorum.")
                comments[code] = f"🤖 {res.text.strip().replace(chr(10), ' ')[:50]}"
            except: comments[code] = f"⚙️ Teknik: {t.get('regime', 'N/A')} (V:{t.get('vol',0):.2f})"
        else:
            comments[code] = f"⚙️ Teknik: {t.get('regime', 'N/A')}"
    return comments

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
    
    available_cash = CURRENT_PORTFOLIO.get("CASH", 0)
    effective_capital = START_CAPITAL + available_cash
    target = []
    for s in selected:
        price = techs[s]['price']
        vol = techs[s]['vol']
        # Dinamik Stop-Loss: Volatilite arttıkça stop mesafesini genişlet
        stop_val = safe_round(price - (techs[s]['atr'] * (2.0 + (vol * 2.0))))
        target.append({"code": s, "lot": math.floor((effective_capital * weights[s]) / price), "price": price, "stop": stop_val})

    orders = []
    for t in target:
        curr = CURRENT_PORTFOLIO.get(t['code'], 0)
        if t['lot'] > curr: orders.append({"type": "BUY", "code": t['code'], "lot": round(t['lot'] - curr, 4)})
    
    ai_comments = get_ai_comments(orders, techs)
    md = f"## 🏦 Apex Terminal v25.3 ({PORTFOLIO_TYPE})\n| İşlem | Hisse | Adet | Analiz |\n| :--- | :--- | :--- | :--- |\n"
    for o in orders:
        md += f"| {'🟩 AL' if o['type'] == 'BUY' else '🟥 SAT'} | **{o['code']}** | {o['lot']} | {ai_comments.get(o['code'], '---')} |\n"
    
    md += "\n\n### 🎯 HEDEF PORTFÖY VE DİNAMİK STOP\n| Hisse | Lot | Fiyat | Dinamik Stop |\n| :--- | :--- | :--- | :--- |\n"
    for t in target:
        md += f"| **{t['code']}** | {t['lot']} | {t['price']} | {t['stop']} |\n"

    md += """
### 📝 Terimler Sözlüğü
* **ATR (Average True Range):** Hissenin son dönemdeki ortalama oynaklık aralığı. Stop-loss seviyesini belirlerken fiyatın doğal dalgalanmalarından etkilenmemek için kullanılır.
* **Vol (Volatilite):** Hissenin fiyatındaki istatistiksel oynaklık (yıllık standart sapma). Yüksek olması yüksek risk/hareketlilik gösterir.
* **Dinamik Stop:** ATR'nin volatilite ile ölçeklenmiş hali. Hisse ne kadar oynaksa stop mesafesi o kadar geniş, stabilse o kadar dardır.
* **TREND:** Fiyatın 200 günlük ortalamanın üzerinde olduğu ve güçlü momentum sergilediği yükseliş evresi.
* **WEAK:** Teknik göstergelerin zayıf sinyaller verdiği veya düşüş eğilimindeki evre.
"""
    
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f: f.write(md)
    else: print(md)

if __name__ == "__main__":
    main()
