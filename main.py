# -*- coding: utf-8 -*-
import os, sys, json, math, time
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import requests

# ================================
# SAFE IMPORT Koruması
# ================================
try:
    from google import genai
except ImportError:
    genai = None

# ================================
# CONFIG & STATE
# ================================
START_CAPITAL = 100000     
MAX_PORTFOLIO_SIZE = 5     
LOOKBACK_DAYS = 252        

# GÜNCEL PORTFÖY DAĞILIMI
CURRENT_PORTFOLIO = {
    "ASELS.IS": 71,
    "ASTOR.IS": 26,
    "BIMAS.IS": 5,
    "KATMR.IS": 1000,
    "AKSEN.IS": 20,
    "OTKAR.IS": 3,
    "FROTO.IS": 10,
    "SISE.IS": 23,
    "ODINE.IS": 1,
    "MIATK.IS": 21,
    "TUPRS.IS": 3,
    "ALTNY.IS": 42.5,
    "THYAO.IS": 2,
    "KCHOL.IS": 3,
    "ISMEN.IS": 12,
    "RALYH.IS": 2.28,
    "SOKM.IS": 10,
    "KONTR.IS": 55,
    "MAVI.IS": 10,
    "PASEU.IS": 3,
    "EMPAE.IS": 6,
    "ONRYT.IS": 4,
    "AKSA.IS": 20,
    "SDTTR.IS": 1,
    "NETCD.IS": 1,
    "RUZYE.IS": 10,
    "TRALT.IS": 1,
    "UCAYM.IS": 1,
    "CASH": 50000  # Sistemdeki güncel serbest nakit miktarı
}

# ================================
# SAFE HELPERS (Hata Alınan Kısım Düzeltildi)
# ================================
def safe_float(x, default=0.0):
    try:
        return float(x)
    except:
        return default

def safe_round(x, n=2):
    try:
        if pd.notna(x):
            return round(float(x), n)
        else:
            return 0
    except:
        return 0

# ================================
# MACRO ENGINE
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
# TECHNICAL ENGINE
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
# FUNDAMENTAL ENGINE (PETER LYNCH)
# ================================
def get_fundamental(ticker_obj, code, current_inflation):
    clean_code = code.replace(".IS", "")
    fund_data = {"real_growth": 0, "leverage": 0, "source": "NONE"}

    try:
        res = requests.get(
            f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={clean_code}&exchange=TRY&financialGroup=XI_29&year1={datetime.now().year-1}&period1=12&year2={datetime.now().year-2}&period2=12",
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=5
        )

        data = res.json()
        raw = data.get('value') or data.get('data') or []

        rev_curr = safe_float(next((i.get('value1') for i in raw if 'SATIŞ GELİRLERİ' in i.get('itemDescTR', '')), 0))
        rev_prev = safe_float(next((i.get('value2') for i in raw if 'SATIŞ GELİRLERİ' in i.get('itemDescTR', '')), 0))

        nom_growth = (rev_curr / rev_prev - 1) * 100 if rev_prev > 0 else 0

        fund_data["real_growth"] = safe_round(((1 + nom_growth/100) / (1 + current_inflation)) - 1) * 100
        fund_data["source"] = "ISYATIRIM"

    except:
        info = getattr(ticker_obj, "fast_info", {}) or {}
        nom_growth = (info.get("revenueGrowth", 0) or 0) * 100

        fund_data["real_growth"] = safe_round(((1 + nom_growth/100) / (1 + current_inflation)) - 1) * 100
        fund_data["source"] = "YFINANCE"

    return fund_data

# ================================
# AI ENGINE (TOPLU / BATCH LOGIC)
# ================================
def ai_call_with_retry(func, code, max_retries=3):
    delay = 2

    for i in range(max_retries):
        try:
            return func()
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                print(f"⏳ Rate Limit ({code}). {delay}sn bekleniyor... (Deneme {i+1}/{max_retries})")
                time.sleep(delay)
                delay *= 2
            else:
                print(f"🩺 DEBUG AI Error for {code}: {error_msg}")
                return "Sistem Onaylı (AI Çevrimdışı)"

    return "Sistem Onaylı (AI Limit Aşıldı)"

def batch_ai_trade_desk_commentary(orders, technicals, fundamentals, api_key):
    """Tüm emirleri tek bir AI isteğinde toplayarak Rate Limit aşımını engeller."""
    if not api_key or genai is None or not orders:
        return {o['code']: "AI Devre Dışı" for o in orders}

    def _call():
        client = genai.Client(api_key=api_key)

        prompt = (
            "Sen bir uzman tradersın. Aşağıdaki hisse emirlerini incele ve HER BİRİ için "
            "profesyonel, tek cümlelik kısa bir onay/yorum yaz.\n\n"
            "SADECE GEÇERLİ BİR JSON FORMATINDA YANIT VER. Başka açıklama yazma.\n"
            "Örnek: {\"AKSA.IS\": \"Güçlü trend ve büyüme verisiyle alım uygun.\", \"THYAO.IS\": \"Satış mantıklı.\"}\n\n"
            "Emirler:\n"
        )

        for o in orders:
            code = o['code']
            tech = technicals.get(code, {})
            fund = fundamentals.get(code, {})
            prompt += f"- {code}: {o['type']} Emri. Teknik Rejim: {tech.get('regime', 'Nötr')}, Reel Büyüme: %{fund.get('real_growth', 0)}.\n"

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        try:
            raw_text = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(raw_text)
        except Exception as e:
            print(f"🩺 DEBUG JSON Parse Error: {e}")
            return {o['code']: "Sistem Onaylı (AI Format Hatası)" for o in orders}

    result = ai_call_with_retry(_call, "TOPLU_AI_ISTEGI")
    
    if isinstance(result, str):
        return {o['code']: result for o in orders}
        
    return result

# ================================
# MAIN ENGINE
# ================================
def main():
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS,BIMAS.IS")
    capital_input = float(os.getenv("PORTFOLIO_CAPITAL", START_CAPITAL))

    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]

    current_inflation = get_tcmb_inflation()
    all_data, scores, fundamentals, technicals = {}, {}, {}, {}

    for code in stock_codes:
        ticker = yf.Ticker(code)
        df = ticker.history(period="2y")

        if not df.empty and len(df) > 200:
            df, tech = get_technical_and_regime(df)
            fund = get_fundamental(ticker, code, current_inflation)

            score = 0
            if tech['regime'] != "RANGE_OR_DOWN": score += 50
            if fund['real_growth'] > 0: score += 50

            technicals[code] = tech
            fundamentals[code] = fund

            if score > 30:
                all_data[code] = df
                scores[code] = score

            time.sleep(1)

    selected_codes = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]

    if not selected_codes:
        print("Uygun hisse bulunamadı.")
        return

    inv_vols = {c: 1/max(technicals[c]['volatility'], 0.01) for c in selected_codes}
    total_inv = sum(inv_vols.values())

    # Kırılgan olabilecek tek satırlık if-else yapısı güvenli hale getirildi
    if total_inv > 0:
        weights = {c: (iv / total_inv) for c, iv in inv_vols.items()}
    else:
        weights = {c: 1/len(inv_vols) for c in inv_vols}

    target_portfolio = []

    for code in selected_codes:
        price = technicals[code]['price']

        lot = math.floor((capital_input * weights[code]) / price) if price > 0 else 0

        target_portfolio.append({
            "code": code,
            "price": price,
            "weight": weights[code],
            "lot": lot,
            "stop": max(0, safe_round(price - (technicals[code]['atr'] * 2.5)))
        })

    orders = []

    for item in target_portfolio:
        curr_lot = CURRENT_PORTFOLIO.get(item['code'], 0)

        if item['lot'] > curr_lot:
            orders.append({
                "type": "BUY",
                "code": item['code'],
                "lot": item['lot'] - curr_lot
            })

    for code, lot in CURRENT_PORTFOLIO.items():
        if code != "CASH" and not any(i['code'] == code for i in target_portfolio):
            orders.append({"type": "SELL", "code": code, "lot": lot})

    md = f"## 🏦 Dr. Ömer - Apex Terminal v23.0 (Ultimate Edition)\n"
    md += f"**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"

    md += "### ⚡ İŞLEM EMİRLERİ\n"
    md += "| İşlem | Hisse | Adet | AI Trader Onayı |\n"
    md += "| :--- | :--- | :--- | :--- |\n"

    ai_comments = batch_ai_trade_desk_commentary(orders, technicals, fundamentals, api_key)

    for o in orders:
        ai_msg = ai_comments.get(o['code'], "Sistem Onaylı (Yorum Yok)")
        md += f"| {'🟩 AL' if o['type']=='BUY' else '🟥 SAT'} | **{o['code']}** | {o['lot']} | {ai_msg} |\n"

    md += "\n---\n### 🎯 HEDEF PORTFÖY\n"
    md += "| Hisse | Ağırlık | Lot | İzleyen Stop |\n"
    md += "| :--- | :--- | :--- | :--- |\n"

    for r in target_portfolio:
        md += f"| **{r['code']}** | %{r['weight']*100:.1f} | {r['lot']} | {r['stop']} ₺ |\n"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")

    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(md)

if __name__ == "__main__":
    main()
