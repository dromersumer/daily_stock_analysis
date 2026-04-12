# -*- coding: utf-8 -*-
import os, json, math
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np

# DÜZELTME #6: google.genai modül düzeyine taşındı
try:
    from google import genai as google_genai
except ImportError:
    google_genai = None

from data_provider.wolfram_provider import WolframValuationProvider

# --- 1. PORTFÖY TİPİ VE DİNAMİK DEĞİŞKENLER ---
PORTFOLIO_TYPE = os.getenv("PORTFOLIO_TYPE", "BIST").upper()
START_CAPITAL = float(os.getenv("PORTFOLIO_CAPITAL", "100000"))
MAX_PORTFOLIO_SIZE = 19
MAX_WEIGHT_PER_STOCK = 0.35
LOOKBACK_DAYS = 252
USE_AI = os.getenv("USE_AI", "false").lower() == "true"
CURRENCY = "$" if PORTFOLIO_TYPE == "ABD" else "₺"

# --- GÜNCEL PORTFÖY (100.000 ₺ NAKİT GÜNCELLEMESİYLE) ---
if PORTFOLIO_TYPE == "ABD":
    CURRENT_PORTFOLIO = {
        "QQQM": 3, "NVDA": 3.539, "AVGO": 1.526, "SPUS": 9, "INTC": 7,
        "GOOG": 1.0063, "MU": 0.54, "BABA": 1.278, "LITE": 0.125,
        "SMH": 0.257, "SCHD": 3, "CAT": 0.1, "CHAT": 1, "XLE": 1,
        "NVTS": 6, "QQQI": 1, "GNRC": 0.25, "REMX": 0.5, "TSM": 0.1,
        "ADI": 0.09, "RGTI": 2, "UUUU": 1, "QBTS": 1, "REI": 4,
        "CASH": 10000
    }
else:
    CURRENT_PORTFOLIO = {
        "AKSEN.IS": 10,    "ALTNY.IS": 67.5,  "ASELS.IS": 71,
        "ASTOR.IS": 30,    "BIMAS.IS": 5,     "EREGL.IS": 135,
        "FROTO.IS": 10,    "ISDMR.IS": 82,    "ISMEN.IS": 13,
        "KATMR.IS": 1000,  "KCHOL.IS": 6,     "KONTR.IS": 115,
        "MIATK.IS": 27,    "ODINE.IS": 1,     "OTKAR.IS": 3,
        "RALYH.IS": 12.28, "SISE.IS": 36,     "THYAO.IS": 2,
        "TUPRS.IS": 10,    "CASH": 100000      # 100.000 TL Nakit Güncellendi
    }

def safe_float(x, d=0.0):
    try: return float(x)
    except: return d

def safe_round(x, n=2):
    try:
        if pd.notna(x): return round(float(x), n)
        return 0
    except: return 0

def get_technical(df):
    close = df['Close']
    df['ema200'] = close.ewm(span=200).mean()
    tr = pd.concat(
        [df['High'] - df['Low'],
         (df['High'] - close.shift()).abs(),
         (df['Low'] - close.shift()).abs()],
        axis=1
    ).max(axis=1)

    df['atr'] = tr.rolling(14).mean().dropna()
    df['vol'] = close.pct_change().rolling(20).std() * np.sqrt(LOOKBACK_DAYS)

    last = df.iloc[-1]
    mom_20 = safe_float(close.pct_change(20).iloc[-1])
    mom_60 = safe_float(close.pct_change(60).iloc[-1]) if len(close) > 60 else 0
    regime = "TREND" if last['Close'] > last['ema200'] and mom_20 > 0 else "WEAK"
    return {
        "price": safe_round(last['Close']),
        "atr": safe_round(last['atr']),
        "vol": safe_float(last['vol']),
        "mom_60": mom_60,
        "regime": regime
    }

def get_ai_comments(orders):
    wolfram = WolframValuationProvider()
    comments = {}
    for o in orders:
        hisse_kodu = o['code'].replace(".IS", "")
        wolfram_notu = wolfram.get_stock_valuation(hisse_kodu) or ""

        if "Veri bulunamadı" in wolfram_notu or "Hata" in wolfram_notu or not wolfram_notu:
            wolfram_ozet = "Analiz Bekleniyor"
        else:
            wolfram_ozet = wolfram_notu.split('\n')[0][:50]

        if USE_AI and google_genai is not None:
            try:
                api_key = os.getenv("GEMINI_API_KEY")
                if api_key:
                    client = google_genai.Client(api_key=api_key)
                    prompt = f"{o['code']} için şu Wolfram verisine dayanarak kısa yatırım yorumu yap: {wolfram_notu[:200]}"
                    res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                    comments[o['code']] = f"🤖 {res.text[:60]}..."
                    continue
            except Exception: pass

        comments[o['code']] = f"📊 Wolfram: {wolfram_ozet}..."
    return comments

def apply_weight_cap_and_renormalize(weights, cap=MAX_WEIGHT_PER_STOCK):
    weights = dict(weights)
    for _ in range(len(weights)):
        capped = {s: min(w, cap) for s, w in weights.items()}
        total = sum(capped.values())
        if total == 0: break
        normalized = {s: w / total for s, w in capped.items()}
        if all(w <= cap + 1e-9 for w in normalized.values()):
            return normalized
        weights = normalized
    return normalized

def main():
    default_list = "AKSEN.IS,ALTNY.IS,ASELS.IS,ASTOR.IS,BIMAS.IS,EREGL.IS,FROTO.IS,ISDMR.IS,ISMEN.IS,KATMR.IS,KCHOL.IS,KONTR.IS,MIATK.IS,ODINE.IS,OTKAR.IS,RALYH.IS,SISE.IS,THYAO.IS,TUPRS.IS"
    stock_input = os.getenv("STOCK_LIST", default_list)

    stocks = [s.strip().upper() for s in stock_input.split(",") if s.strip() and s.strip().upper() != "CASH"]

    data = yf.download(tickers=" ".join(stocks), period="2y", group_by="ticker")
    if data is None or data.empty: return

    techs, scores = {}, {}
    for s in stocks:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if s in data.columns.get_level_values(0): df = data[s].copy()
                else: continue
            else: df = data.copy()

            if df.empty or len(df) < 200:
                print(f"[UYARI] {s}: Yetersiz veri ({len(df)} gün), analiz dışı bırakıldı.")
                continue

            t = get_technical(df.dropna())
            techs[s] = t
            score = ((1 if t['regime'] == "TREND" else 0) * 40 + (max(1 - t['vol'], 0) * 30) + (min(max(t['mom_60'] / 0.5, 0), 1) * 30))
            if score > 0: scores[s] = score
        except Exception: continue

    selected = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]
    if not selected: return

    all_vols = [techs[s]['vol'] for s in techs if techs[s]['vol'] > 0]
    MIN_VOL = max(np.percentile(all_vols, 25) if len(all_vols) >= 4 else 0.05, 0.05)
    inv = {s: 1 / max(techs[s]['vol'], MIN_VOL) for s in selected}
    total_inv = sum(inv.values())
    raw_weights = {s: inv[s] / total_inv for s in selected} if total_inv > 0 else {s: 1 / len(selected) for s in selected}

    weights = apply_weight_cap_and_renormalize(raw_weights)

    available_cash = CURRENT_PORTFOLIO.get("CASH", 0)
    effective_capital = START_CAPITAL + available_cash

    target = []
    for s in selected:
        price = techs[s]['price']
        lot = math.floor((effective_capital * weights[s]) / price) if price >= 1.0 else 0
        target.append({"code": s, "lot": lot, "weight": weights[s], "price": price, "stop": safe_round(price - techs[s]['atr'] * 2.5)})

    target = sorted(target, key=lambda x: x['weight'], reverse=True)
    orders = []
    for t in target:
        curr = CURRENT_PORTFOLIO.get(t['code'], 0)
        if t['lot'] > curr:
            orders.append({"type": "BUY", "code": t['code'], "lot": round(t['lot'] - curr, 4)})

    for c, l in CURRENT_PORTFOLIO.items():
        if c != "CASH" and l > 0 and not any(t['code'] == c for t in target):
            orders.append({"type": "SELL", "code": c, "lot": l})

    ai_comments = get_ai_comments(orders)

    md = f"## 🏦 Apex Terminal v25.2 ({PORTFOLIO_TYPE} Quant Engine)\n"
    md += f"Tarih: {datetime.now().strftime('%d-%m-%Y %H:%M')}\n"
    md += f"Başlangıç Sermayesi: {START_CAPITAL:,.2f} {CURRENCY}\n"
    md += f"Mevcut Nakit: {available_cash:,.2f} {CURRENCY}\n"
    md += f"Etkin Sermaye: {effective_capital:,.2f} {CURRENCY}\n\n"
    md += "### ⚡ İŞLEM EMİRLERİ (Wolfram Analizli)\n"
    md += "| İşlem | Hisse | Adet | AI / Wolfram Değerleme |\n"
    md += "| :--- | :--- | :--- | :--- |\n"

    for o in orders:
        islem = "🟩 AL" if o['type'] == "BUY" else "🟥 SAT"
        md += f"| {islem} | **{o['code']}** | {o['lot']} | {ai_comments.get(o['code'], 'Analiz Bekleniyor')} |\n"

    md += "\n---\n### 🎯 HEDEF PORTFÖY\n"
    md += "| Hisse | Ağırlık | Lot | Son Fiyat | İzleyen Stop |\n"
    md += "| :--- | :--- | :--- | :--- | :--- |\n"
    for t in target:
        md += f"| **{t['code']}** | %{t['weight']*100:.1f} | {t['lot']} | {t['price']} {CURRENCY} | {t['stop']} {CURRENCY} |\n"

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f: f.write(md)
    else: print(md)

if __name__ == "__main__":
    main()
