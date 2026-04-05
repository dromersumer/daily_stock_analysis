# -*- coding: utf-8 -*-
import os, json, math
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np

# --- 1. PORTFÖY TİPİ VE DİNAMİK DEĞİŞKENLER ---
PORTFOLIO_TYPE = os.getenv("PORTFOLIO_TYPE", "BIST").upper() # Varsayılan BIST
START_CAPITAL = float(os.getenv("PORTFOLIO_CAPITAL", "100000")) 
MAX_PORTFOLIO_SIZE = 20
MAX_WEIGHT_PER_STOCK = 0.35
LOOKBACK_DAYS = 252
USE_AI = os.getenv("USE_AI", "false").lower() == "true"
CURRENCY = "$" if PORTFOLIO_TYPE == "ABD" else "₺"

# Dinamik Portföy Seçimi
if PORTFOLIO_TYPE == "ABD":
    CURRENT_PORTFOLIO = {
        "QQQM": 3, "NVDA": 3.539, "AVGO": 1.526, "SPUS": 9, "INTC": 7,
        "GOOG": 1.0063, "MU": 0.54, "BABA": 1.278, "LITE": 0.125,
        "SMH": 0.257, "SCHD": 3, "CAT": 0.1, "CHAT": 1, "XLE": 1,
        "NVTS": 6, "QQQI": 1, "GNRC": 0.25, "REMX": 0.5, "TSM": 0.1,
        "ADI": 0.09, "RGTI": 2, "UUUU": 1, "QBTS": 1, "REI": 4,
        "CASH": 10000 # Örnek ABD nakitiniz
    }
else:
    CURRENT_PORTFOLIO = {
        "ASELS.IS": 71, "ASTOR.IS": 26, "BIMAS.IS": 5, "KATMR.IS": 1000,
        "AKSEN.IS": 20, "OTKAR.IS": 3, "FROTO.IS": 10, "SISE.IS": 23,
        "ODINE.IS": 1, "MIATK.IS": 21, "TUPRS.IS": 3, "ALTNY.IS": 42.5,
        "THYAO.IS": 2, "KCHOL.IS": 3, "ISMEN.IS": 12, "RALYH.IS": 2.28,
        "SOKM.IS": 10, "KONTR.IS": 55, "MAVI.IS": 10, "PASEU.IS": 3,
        "EMPAE.IS": 6, "ONRYT.IS": 4, "AKSA.IS": 20, "SDTTR.IS": 1,
        "NETCD.IS": 1, "RUZYE.IS": 10, "TRALT.IS": 1, "UCAYM.IS": 1,
        "CASH": 50000
    }

def safe_float(x, d=0.0):
    try:
        return float(x)
    except:
        return d

def safe_round(x, n=2):
    try:
        if pd.notna(x):
            return round(float(x), n)
        return 0
    except:
        return 0

def get_technical(df):
    close = df['Close']
    df['ema200'] = close.ewm(span=200).mean()

    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - close.shift()).abs(),
        (df['Low'] - close.shift()).abs()
    ], axis=1).max(axis=1)

    df['atr'] = tr.rolling(14).mean().bfill()
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
    if not USE_AI or not orders:
        return {o['code']: "Sistem Onaylı (AI Kapalı)" for o in orders}

    try:
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {o['code']: "Sistem Onaylı (API Key Yok)" for o in orders}

        client = genai.Client(api_key=api_key)

        # --- 2. YAPAY ZEKA BAĞLAMI ---
        context = "BIST hisseleri ve Türkiye piyasası" if PORTFOLIO_TYPE == "BIST" else "ABD Teknoloji/ETF piyasası ve küresel trendler"
        
        prompt = f"Şu {context} işlemleri için kısa, profesyonel gerekçeler üret. SADECE bir JSON objesi döndür. Key: hisse kodu, Value: gerekçe.\n"
        for o in orders:
            prompt += f"{o['code']} {o['type']}\n"

        res = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        txt = res.text.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(txt)
            if isinstance(parsed, dict):
                return parsed
        except:
            pass

        return {o['code']: "Sistem Onaylı (AI Parse Hatası)" for o in orders}

    except Exception:
        return {o['code']: "Sistem Onaylı (AI Hata)" for o in orders}

def main():
    # Varsayılan listeler pazar tipine göre belirleniyor
    default_list = "ADI,AVGO,CAT,CHAT,GNRC,GOOG,INTC,LITE,MU,NVDA,NVTS,QQQI,QQQM,REMX,SCHD,SMH,SPUS,TSM,XLE" if PORTFOLIO_TYPE == "ABD" else "THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS,BIMAS.IS"
    stock_input = os.getenv("STOCK_LIST", default_list)
    
    stocks = [s.strip().upper() for s in stock_input.split(",") if s.strip()]

    # ABD pazarında ".IS" olanlar varsa temizle (olası bir hata girişini önlemek için)
    if PORTFOLIO_TYPE == "ABD":
        stocks = [s.replace(".IS", "") for s in stocks]

    data = yf.download(
        tickers=" ".join(stocks),
        period="2y",
        group_by="ticker",
        threads=False
    )

    if data is None or data.empty or not hasattr(data, "columns"):
        print("KRİTİK HATA: Veri alınamadı")
        return

    techs = {}
    scores = {}

    cols_lvl0 = []
    if isinstance(data.columns, pd.MultiIndex):
        try:
            cols_lvl0 = list(data.columns.get_level_values(0))
        except:
            print("KRİTİK HATA: MultiIndex bozuk")
            return

    for s in stocks:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if s not in cols_lvl0:
                    continue
                df = data[s].copy()
            else:
                if len(stocks) == 1 and s == stocks[0]:
                    df = data.copy()
                else:
                    continue

            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(col in df.columns for col in required_cols):
                continue

            df = df[required_cols].dropna()

            if df.empty or len(df) < 200:
                continue

            t = get_technical(df)
            techs[s] = t

            trend_score = 1 if t['regime'] == "TREND" else 0
            vol_score = max(1 - t['vol'], 0)
            mom_norm = min(max(t['mom_60'] / 0.50, 0), 1.0)

            score = (trend_score * 40) + (vol_score * 30) + (mom_norm * 30)

            if score > 0:
                scores[s] = score

        except Exception:
            continue

    selected = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]

    if not selected:
        print("Uygun hisse yok")
        return

    all_vols = [techs[s]['vol'] for s in techs if techs[s]['vol'] > 0]
    all_vols = [v for v in all_vols if not pd.isna(v)]

    if len(all_vols) >= 4:
        p = np.percentile(all_vols, 25)
        MIN_VOL = max(p if not pd.isna(p) else 0.05, 0.05)
    else:
        MIN_VOL = 0.05

    inv = {}
    for s in selected:
        v = techs[s]['vol']
        if pd.isna(v) or v <= 0:
            v = MIN_VOL
        inv[s] = 1 / max(v, MIN_VOL)

    total_inv = sum(inv.values())

    if total_inv > 0:
        weights = {s: inv[s] / total_inv for s in selected}
    else:
        if len(selected) == 0:
            print("KRİTİK HATA: selected boş")
            return
        weights = {s: 1/len(selected) for s in selected}

    for _ in range(10):
        overweight = {s: w for s, w in weights.items() if w > MAX_WEIGHT_PER_STOCK}
        if not overweight:
            break

        excess = sum(w - MAX_WEIGHT_PER_STOCK for w in overweight.values())
        if excess < 1e-6:
            break

        for s in overweight:
            weights[s] = MAX_WEIGHT_PER_STOCK

        underweight = {s: w for s, w in weights.items() if w < MAX_WEIGHT_PER_STOCK}
        total_under = sum(underweight.values())

        if total_under > 0:
            for s in underweight:
                weights[s] += (weights[s] / total_under) * excess
        else:
            if len(weights) == 0:
                print("KRİTİK HATA: weights boş")
                return
            equal_add = excess / len(weights)
            for s in weights:
                weights[s] += equal_add

    weights = {s: (0 if pd.isna(w) else w) for s, w in weights.items()}
    total_w = sum(weights.values())

    if total_w > 0:
        weights = {s: w / total_w for s, w in weights.items()}
    else:
        print("KRİTİK HATA: normalize başarısız")
        return

    target = []
    for s in selected:
        price = techs[s]['price']

        if pd.isna(price) or price < 1.0:
            lot = 0
        else:
            lot = math.floor((START_CAPITAL * weights[s]) / price)

        target.append({
            "code": s,
            "lot": lot,
            "weight": weights[s],
            "price": price, # --- SON FİYAT EKLENDİ ---
            "stop": safe_round(price - techs[s]['atr'] * 2.5)
        })

    target = sorted(target, key=lambda x: x['weight'], reverse=True)

    orders = []

    for t in target:
        curr = CURRENT_PORTFOLIO.get(t['code'], 0)
        if t['lot'] > curr:
            orders.append({"type": "BUY", "code": t['code'], "lot": round(t['lot'] - curr, 4)})

    for c, l in CURRENT_PORTFOLIO.items():
        if c != "CASH" and not any(t['code'] == c for t in target):
            orders.append({"type": "SELL", "code": c, "lot": l})

    ai_comments = get_ai_comments(orders)

    # --- 3. RAPORLAMA (DİNAMİK PARA BİRİMİ VE SON FİYAT İLE) ---
    md = f"## 🏦 Apex Terminal v25.0 ({PORTFOLIO_TYPE} Quant Engine)\n"
    md += f"Tarih: {datetime.now().strftime('%d-%m-%Y %H:%M')}\n"
    md += f"Sermaye: {START_CAPITAL:,.2f} {CURRENCY}\n\n"

    md += "### ⚡ İŞLEM EMİRLERİ\n"
    md += "| İşlem | Hisse | Adet | AI |\n"
    md += "| :--- | :--- | :--- | :--- |\n"

    for o in orders:
        islem = "🟩 AL" if o['type'] == "BUY" else "🟥 SAT"
        md += f"| {islem} | **{o['code']}** | {o['lot']} | {ai_comments.get(o['code'], 'Sistem Onaylı')} |\n"

    md += "\n---\n### 🎯 HEDEF PORTFÖY\n"
    md += f"| Hisse | Ağırlık | Lot | Son Fiyat | İzleyen Stop |\n"
    md += f"| :--- | :--- | :--- | :--- | :--- |\n"

    for t in target:
        md += f"| **{t['code']}** | %{t['weight']*100:.1f} | {t['lot']} | {t['price']} {CURRENCY} | {t['stop']} {CURRENCY} |\n"

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md)

if __name__ == "__main__":
    main()
