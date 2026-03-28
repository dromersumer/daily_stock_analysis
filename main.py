# -*- coding: utf-8 -*-
import os, json, math, time
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import requests

# ================================
# CONFIG
# ================================
START_CAPITAL = 100000
MAX_PORTFOLIO_SIZE = 5
LOOKBACK_DAYS = 252
USE_AI = os.getenv("USE_AI", "false").lower() == "true"

# ================================
# PORTFOLIO
# ================================
CURRENT_PORTFOLIO = {
    "ASELS.IS": 71, "ASTOR.IS": 26, "BIMAS.IS": 5, "KATMR.IS": 1000,
    "AKSEN.IS": 20, "OTKAR.IS": 3, "FROTO.IS": 10, "SISE.IS": 23,
    "ODINE.IS": 1, "MIATK.IS": 21, "TUPRS.IS": 3, "ALTNY.IS": 42.5,
    "THYAO.IS": 2, "KCHOL.IS": 3, "ISMEN.IS": 12, "RALYH.IS": 2.28,
    "SOKM.IS": 10, "KONTR.IS": 55, "MAVI.IS": 10, "CASH": 25000
}

# ================================
# HELPERS
# ================================
def safe_float(x, default=0.0):
    try: return float(x)
    except: return default

def safe_round(x, n=2):
    try: return round(float(x), n) if pd.notna(x) else 0
    except: return 0

# ================================
# MACRO
# ================================
def get_tcmb_inflation():
    try:
        api_key = os.getenv("EVDS_API_KEY")
        if not api_key: return 0.50

        url = f"https://evds2.tcmb.gov.tr/service/evds/series=TP.TUFE1&last=13&type=json&key={api_key}"
        res = requests.get(url, timeout=10)
        data = res.json()

        items = data.get('items') or data.get('data') or []
        values = [safe_float(x.get('TP_TUFE1')) for x in items if x.get('TP_TUFE1')]

        return safe_round((values[-1] / values[0]) - 1, 4) if len(values) >= 12 else 0.50
    except:
        return 0.50

# ================================
# TECHNICAL
# ================================
def get_technical_and_regime(df):
    close = df['Close']
    df['ema200'] = close.ewm(span=200, adjust=False).mean()

    tr = pd.concat([
        df['High']-df['Low'],
        (df['High']-close.shift(1)).abs(),
        (df['Low']-close.shift(1)).abs()
    ], axis=1).max(axis=1)

    df['atr'] = tr.rolling(14).mean().bfill()
    df['volatility'] = close.pct_change().rolling(20).std() * np.sqrt(LOOKBACK_DAYS)

    short_mom = close.pct_change(20).iloc[-1] if len(close) > 20 else 0
    last = df.iloc[-1]

    vol = safe_float(last['volatility'])

    if last['Close'] > last['ema200'] and short_mom > 0 and vol < 0.35:
        regime = "TREND_LOW_VOL"
    elif last['Close'] > last['ema200'] and short_mom > 0:
        regime = "TREND_HIGH_VOL"
    else:
        regime = "RANGE_OR_DOWN"

    return df, {
        "price": safe_round(last['Close']),
        "atr": safe_round(last['atr']),
        "volatility": safe_round(vol),
        "regime": regime
    }

# ================================
# FUNDAMENTAL
# ================================
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})

def get_fundamental(code, inflation):
    clean_code = code.replace(".IS", "")

    try:
        url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={clean_code}&exchange=TRY&financialGroup=XI_29&year1={datetime.now().year-1}&period1=12&year2={datetime.now().year-2}&period2=12"
        res = session.get(url, timeout=5)
        data = res.json()

        raw = data.get('value') or data.get('data') or []

        rev_curr = safe_float(next((i.get('value1') for i in raw if 'SATIŞ' in i.get('itemDescTR', '')), 0))
        rev_prev = safe_float(next((i.get('value2') for i in raw if 'SATIŞ' in i.get('itemDescTR', '')), 0))

        if rev_prev <= 0:
            return {"real_growth": 0}

        nom_growth = (rev_curr / rev_prev - 1)
        real = ((1 + nom_growth) / (1 + inflation)) - 1

        return {"real_growth": safe_round(real * 100)}
    except:
        return {"real_growth": 0}

# ================================
# AI (SAFE)
# ================================
def get_ai_comments(orders):
    if not USE_AI:
        return {o['code']: "Sistem Onaylı" for o in orders}

    try:
        from google import genai
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        prompt = "JSON kısa yorum ver:\n"
        for o in orders:
            prompt += f"{o['code']} {o['type']}\n"

        res = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        txt = res.text.strip().replace("```json", "").replace("```", "")
        return json.loads(txt)

    except Exception as e:
        print("AI FAIL:", e)
        return {o['code']: "Sistem Onaylı" for o in orders}

# ================================
# MAIN
# ================================
def main():
    stock_input = os.getenv("STOCK_LIST", "THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS,BIMAS.IS")
    capital = float(os.getenv("PORTFOLIO_CAPITAL", START_CAPITAL))
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]

    inflation = get_tcmb_inflation()

    # 🔥 TEK REQUEST
    data = yf.download(
        tickers=" ".join(stock_codes),
        period="2y",
        group_by="ticker",
        threads=False
    )

    scores, technicals = {}, {}

    for code in stock_codes:
        try:
            df = data[code].dropna()
        except:
            continue

        if len(df) < 200:
            continue

        df, tech = get_technical_and_regime(df)
        fund = get_fundamental(code, inflation)

        score = 0
        if tech['regime'] != "RANGE_OR_DOWN": score += 50
        if fund['real_growth'] > 0: score += 50

        if score > 30:
            scores[code] = score
            technicals[code] = tech

    selected = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]

    if not selected:
        print("Hisse yok")
        return

    inv_vols = {}
    for c in selected:
        vol = max(safe_float(technicals[c]['volatility']), 0.01)
        inv_vols[c] = 1 / vol

    total = sum(inv_vols.values())
    weights = {c: inv_vols[c]/total for c in selected}

    target = []
    for c in selected:
        price = technicals[c]['price']
        lot = math.floor((capital * weights[c]) / price) if price > 0 else 0

        target.append({
            "code": c,
            "lot": lot,
            "weight": weights[c],
            "stop": safe_round(price - technicals[c]['atr'] * 2.5)
        })

    orders = []

    for t in target:
        curr = CURRENT_PORTFOLIO.get(t['code'], 0)
        if t['lot'] > curr:
            orders.append({"type": "BUY", "code": t['code'], "lot": t['lot'] - curr})

    for code, lot in CURRENT_PORTFOLIO.items():
        if code != "CASH" and not any(t['code'] == code for t in target):
            orders.append({"type": "SELL", "code": code, "lot": lot})

    # AI SAFE
    ai = get_ai_comments(orders)

    md = f"## 🏦 Apex Terminal v23.1\n\n"
    md += "### ⚡ İŞLEMLER\n"

    for o in orders:
        md += f"- {o['type']} {o['code']} ({o['lot']}) → {ai.get(o['code'])}\n"

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(md)

if __name__ == "__main__":
    main()
