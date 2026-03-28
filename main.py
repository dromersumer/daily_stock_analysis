# -*- coding: utf-8 -*-
import os, json, math
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import requests

START_CAPITAL = 100000
MAX_PORTFOLIO_SIZE = 5
LOOKBACK_DAYS = 252
USE_AI = os.getenv("USE_AI", "false").lower() == "true"

CURRENT_PORTFOLIO = {
    "ASELS.IS": 71, "ASTOR.IS": 26, "BIMAS.IS": 5, "KATMR.IS": 1000,
    "AKSEN.IS": 20, "OTKAR.IS": 3, "FROTO.IS": 10, "SISE.IS": 23,
    "ODINE.IS": 1, "MIATK.IS": 21, "TUPRS.IS": 3, "ALTNY.IS": 42.5,
    "THYAO.IS": 2, "KCHOL.IS": 3, "ISMEN.IS": 12, "RALYH.IS": 2.28,
    "SOKM.IS": 10, "KONTR.IS": 55, "MAVI.IS": 10, "CASH": 25000
}

# ======================
# HELPERS
# ======================
def safe_float(x, d=0): 
    try: return float(x)
    except: return d

def safe_round(x, n=2):
    try: return round(float(x), n) if pd.notna(x) else 0
    except: return 0

# ======================
# TECHNICAL
# ======================
def get_technical(df):
    close = df['Close']
    df['ema200'] = close.ewm(span=200).mean()

    tr = pd.concat([
        df['High']-df['Low'],
        (df['High']-close.shift()).abs(),
        (df['Low']-close.shift()).abs()
    ], axis=1).max(axis=1)

    df['atr'] = tr.rolling(14).mean().bfill()
    df['vol'] = close.pct_change().rolling(20).std() * np.sqrt(LOOKBACK_DAYS)

    last = df.iloc[-1]
    mom = close.pct_change(20).iloc[-1]

    if last['Close'] > last['ema200'] and mom > 0:
        regime = "TREND"
    else:
        regime = "WEAK"

    return {
        "price": safe_round(last['Close']),
        "atr": safe_round(last['atr']),
        "vol": safe_float(last['vol']),
        "regime": regime
    }

# ======================
# FUNDAMENTAL
# ======================
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})

def get_fundamental(code):
    try:
        url = f"https://www.isyatirim.com.tr/_layouts/15/...{code.replace('.IS','')}"
        r = session.get(url, timeout=5)
        data = r.json()
        return {"growth": 10}  # sade fallback
    except:
        return {"growth": 0}

# ======================
# AI (SAFE)
# ======================
def get_ai(orders):
    if not USE_AI:
        return {o['code']: "✔ Sistem" for o in orders}

    try:
        from google import genai
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        prompt = "JSON kısa yorum:\n"
        for o in orders:
            prompt += f"{o['code']} {o['type']}\n"

        res = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        return json.loads(res.text)
    except:
        return {o['code']: "✔ Sistem" for o in orders}

# ======================
# MAIN
# ======================
def main():
    stocks = os.getenv("STOCK_LIST","THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS").split(",")

    data = yf.download(
        tickers=" ".join(stocks),
        period="2y",
        group_by="ticker",
        threads=False
    )

    techs = {}
    scores = {}

    for s in stocks:
        try:
            df = data[s].dropna()
            if len(df) < 200: continue

            t = get_technical(df)
            score = (t['regime']=="TREND")*100

            if score > 0:
                techs[s] = t
                scores[s] = score
        except:
            continue

    selected = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]

    inv = {s: 1/max(techs[s]['vol'],0.01) for s in selected}
    total = sum(inv.values())
    weights = {s: inv[s]/total for s in selected}

    target = []
    for s in selected:
        price = techs[s]['price']
        lot = math.floor((START_CAPITAL*weights[s])/price)

        target.append({
            "code": s,
            "lot": lot,
            "weight": weights[s],
            "stop": safe_round(price - techs[s]['atr']*2.5)
        })

    orders = []

    for t in target:
        curr = CURRENT_PORTFOLIO.get(t['code'],0)
        if t['lot'] > curr:
            orders.append({"type":"BUY","code":t['code'],"lot":t['lot']-curr})

    for c,l in CURRENT_PORTFOLIO.items():
        if c!="CASH" and not any(t['code']==c for t in target):
            orders.append({"type":"SELL","code":c,"lot":l})

    ai = get_ai(orders)

    # ======================
    # HTML UI (🔥 PREMIUM)
    # ======================
    html = f"""
    <style>
    body {{font-family: Arial; background:#0b0f14; color:#e6edf3;}}
    table {{border-collapse: collapse; width:100%; margin-top:10px;}}
    th, td {{padding:10px; text-align:center;}}
    th {{background:#111827; color:#9ca3af;}}
    tr {{border-bottom:1px solid #1f2937;}}
    .buy {{background:#052e16; color:#22c55e; font-weight:bold;}}
    .sell {{background:#3f0d0d; color:#ef4444; font-weight:bold;}}
    .high {{color:#22c55e;}}
    .low {{color:#ef4444;}}
    </style>

    <h2>🏦 Apex Terminal v23.2</h2>
    <b>{datetime.now().strftime('%d-%m-%Y %H:%M')}</b>

    <h3>⚡ İşlem Emirleri</h3>
    <table>
    <tr><th>İşlem</th><th>Hisse</th><th>Lot</th><th>AI</th></tr>
    """

    for o in orders:
        cls = "buy" if o['type']=="BUY" else "sell"
        label = "AL" if o['type']=="BUY" else "SAT"

        html += f"""
        <tr>
        <td class="{cls}">{label}</td>
        <td>{o['code']}</td>
        <td>{o['lot']}</td>
        <td>{ai.get(o['code'])}</td>
        </tr>
        """

    html += "</table><h3>🎯 Hedef Portföy</h3><table>"
    html += "<tr><th>Hisse</th><th>Ağırlık</th><th>Lot</th><th>Stop</th></tr>"

    for t in target:
        w_cls = "high" if t['weight']>0.25 else "low"
        html += f"""
        <tr>
        <td>{t['code']}</td>
        <td class="{w_cls}">%{t['weight']*100:.1f}</td>
        <td>{t['lot']}</td>
        <td>{t['stop']}</td>
        </tr>
        """

    html += "</table>"

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(html)

if __name__ == "__main__":
    main()
