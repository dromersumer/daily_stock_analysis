# -*- coding: utf-8 -*-
import os, math, time, random
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import requests

try:
    from google import genai
except ImportError:
    genai = None

START_CAPITAL = 100000     
MAX_PORTFOLIO_SIZE = 5     
LOOKBACK_DAYS = 252        

CURRENT_PORTFOLIO = {
    "THYAO.IS": 50, "TUPRS.IS": 20, "CASH": 25000    
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
        data = requests.get(url, timeout=10).json()
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
def get_fundamental(ticker_obj, code, inflation):
    try:
        clean = code.replace(".IS", "")
        url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={clean}&exchange=TRY&financialGroup=XI_29&year1={datetime.now().year-1}&period1=12&year2={datetime.now().year-2}&period2=12"
        raw = requests.get(url, timeout=5).json().get('value') or []
        rev_curr = safe_float(next((i.get('value1') for i in raw if 'SATIŞ' in i.get('itemDescTR','')), 0))
        rev_prev = safe_float(next((i.get('value2') for i in raw if 'SATIŞ' in i.get('itemDescTR','')), 0))
        g = (rev_curr / rev_prev - 1) * 100 if rev_prev > 0 else 0
        real = ((1 + g/100) / (1 + inflation) - 1) * 100
        return {"real_growth": safe_round(real)}
    except:
        return {"real_growth": 0}

# ================================
# AI ENGINE (HARDENED)
# ================================
def ai_call_with_retry(func, max_retries=2):
    delay = 10

    for i in range(max_retries):
        try:
            result = func()

            if not result or len(result.strip()) < 5:
                raise RuntimeError("Empty AI response")

            return result

        except Exception as e:
            msg = str(e)

            is_rate = (
                "429" in msg or
                "RESOURCE_EXHAUSTED" in msg.upper()
            )

            print(f"⚠️ AI ERROR: {msg}")

            if is_rate or "Empty AI response" in msg:
                sleep_time = delay + random.uniform(0, 5)
                print(f"⏳ Retry {i+1}: {sleep_time:.1f}s bekleniyor...")
                time.sleep(sleep_time)
                delay *= 2
            else:
                return None

    return None

def get_batch_ai_commentary(client, orders, technicals, fundamentals):
    if not client or not orders:
        return {}

    # 🟢 JITTER DELAY (GITHUB FIX)
    time.sleep(3 + random.uniform(0, 3))

    prompt = [
        "SADECE şu formatta cevap ver:",
        "HISSE: yorum",
        "Başka hiçbir şey yazma."
    ]

    for o in orders:
        c = o['code']
        t = technicals.get(c, {})
        f = fundamentals.get(c, {})
        prompt.append(f"{c} | {o['type']} | {t.get('regime')} | %{f.get('real_growth')}")

    full_prompt = "\n".join(prompt)

    def _call():
        response = client.models.generate_content(
            model="gemini-1.5-flash",  # 🔥 daha stabil model
            contents=full_prompt
        )

        if not response or not getattr(response, "text", None):
            raise RuntimeError("Empty AI response")

        return response.text.strip()

    raw = ai_call_with_retry(_call)

    print(f"\n📩 RAW AI RESPONSE:\n{raw}\n")

    results = {}
    valid_codes = [o['code'] for o in orders]

    if raw:
        for line in raw.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip().upper()
                if k in valid_codes:
                    results[k] = v.strip()

    # 🟢 GUARANTEED OUTPUT
    for c in valid_codes:
        if c not in results:
            results[c] = "AI Yanıt Yok"

    return results

# ================================
# MAIN
# ================================
def main():
    api_key = os.getenv("GEMINI_API_KEY")

    ai_client = None
    if genai and api_key:
        ai_client = genai.Client(api_key=api_key)

    stocks = os.getenv(
        "STOCK_LIST",
        "THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS,BIMAS.IS"
    ).split(",")

    inflation = get_tcmb_inflation()

    techs, funds, scores = {}, {}, {}

    for c in stocks:
        df = yf.Ticker(c).history(period="2y")

        if len(df) > 200:
            df, tech = get_technical_and_regime(df)
            fund = get_fundamental(None, c, inflation)

            score = (tech['regime'] != "RANGE_OR_DOWN") * 50 + (fund['real_growth'] > 0) * 50

            if score > 30:
                techs[c] = tech
                funds[c] = fund
                scores[c] = score

    selected = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]

    inv = {c: 1/max(techs[c]['volatility'],0.01) for c in selected}
    total = sum(inv.values())
    weights = {c:(v/total) for c,v in inv.items()} if total>0 else {c:1/len(inv) for c in inv}

    portfolio = []
    for c in selected:
        p = techs[c]['price']
        lot = math.floor((START_CAPITAL * weights[c]) / p)
        portfolio.append({"code":c,"lot":lot})

    orders = [{"type":"BUY","code":p['code'],"lot":p['lot']} for p in portfolio]

    print("🚀 BATCH AI CALL START")

    ai = get_batch_ai_commentary(ai_client, orders, techs, funds)

    print("\n📊 FINAL OUTPUT\n")

    for o in orders:
        print(o['code'], "→", ai[o['code']])

if __name__ == "__main__":
    main()
