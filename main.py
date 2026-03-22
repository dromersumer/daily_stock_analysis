# -*- coding: utf-8 -*-
import os, sys, json, math, time
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import requests

# ================================
# SAFE IMPORT
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

CURRENT_PORTFOLIO = {
    "THYAO.IS": 50, "TUPRS.IS": 20, "CASH": 25000    
}

def safe_float(x, default=0.0):
    try: return float(x)
    except: return default

def safe_round(x, n=2):
    try: return round(float(x), n) if pd.notna(x) else 0
    except: return 0

# ================================
# MACRO & TECHNICAL
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

    if last['Close'] > last['ema200'] and short_mom > 0 and vol < 0.35: regime = "TREND_LOW_VOL"
    elif last['Close'] > last['ema200'] and short_mom > 0: regime = "TREND_HIGH_VOL"
    else: regime = "RANGE_OR_DOWN"

    return df, {"price": safe_round(last['Close']), "atr": safe_round(last['atr']), "volatility": safe_round(vol), "regime": regime}

# ================================
# FUNDAMENTAL
# ================================
def get_fundamental(ticker_obj, code, current_inflation):
    clean_code = code.replace(".IS", "")
    fund_data = {"real_growth": 0, "source": "NONE"}
    try:
        res = requests.get(
            f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={clean_code}&exchange=TRY&financialGroup=XI_29&year1={datetime.now().year-1}&period1=12&year2={datetime.now().year-2}&period2=12",
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=5
        )
        raw = res.json().get('value') or []
        rev_curr = safe_float(next((i.get('value1') for i in raw if 'SATIŞ GELİRLERİ' in i.get('itemDescTR', '')), 0))
        rev_prev = safe_float(next((i.get('value2') for i in raw if 'SATIŞ GELİRLERİ' in i.get('itemDescTR', '')), 0))
        nom_growth = (rev_curr / rev_prev - 1) * 100 if rev_prev > 0 else 0
        fund_data["real_growth"] = safe_round(((1 + nom_growth/100) / (1 + current_inflation)) - 1) * 100
    except:
        info = getattr(ticker_obj, "fast_info", {}) or {}
        nom_growth = (info.get("revenueGrowth", 0) or 0) * 100
        fund_data["real_growth"] = safe_round(((1 + nom_growth/100) / (1 + current_inflation)) - 1) * 100
    return fund_data

# ================================
# AI ENGINE (BULLETPROOF BATCH EDITION)
# ================================
def ai_call_with_retry(func, max_retries=3):
    delay = 15 

    for i in range(max_retries):
        try:
            return func()
        except Exception as e:
            error_msg = str(e)
            is_rate_limit = (getattr(e, 'code', None) == 429 or getattr(e, 'status_code', None) == 429 or "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg.upper())

            if is_rate_limit:
                print(f"⏳ BATCH API Rate Limit. {delay}sn bekleniyor... (Deneme {i+1}/{max_retries})")
                time.sleep(delay)
                delay *= 2
                continue
            else:
                print(f"🩺 DEBUG AI Error: {error_msg}")
                return None
    return None

def get_batch_ai_commentary(client, orders, technicals, fundamentals):
    if not client or not orders:
        return {}

    # 🟢 Elite Prompting: Hard Constraints Eklenmiş Hali
    prompt_lines = [
        "Sen uzman bir borsa tradersın. Aşağıdaki hisse emirleri için matematiksel verilere dayalı, tek cümlelik profesyonel gerekçeler sun.",
        "DİKKAT: SADECE aşağıdaki formatta cevap ver. Farklı bir format üretirsen, ekstra açıklama veya başlık eklersen cevap geçersiz sayılacaktır.",
        "FORMAT:",
        "HISSE_KODU: Yorum",
        "-------------------",
        "VERİLER:"
    ]
    
    # 🟢 Token Güvenliği: Ne olursa olsun limitli sayıda hisse gönder
    safe_orders = orders[:10] 
    valid_codes = [o['code'] for o in safe_orders]
    
    for o in safe_orders:
        code = o['code']
        tech = technicals.get(code, {})
        fund = fundamentals.get(code, {})
        prompt_lines.append(f"Hisse: {code} | İşlem: {o['type']} | Rejim: {tech.get('regime', 'Nötr')} | Reel Büyüme: %{fund.get('real_growth', 0)}")

    full_prompt = "\n".join(prompt_lines)

    def _call():
        response = client.models.generate_content(model="gemini-2.0-flash", contents=full_prompt)
        return (response.text or "").strip()

    raw_response = ai_call_with_retry(_call)
    
    # 🟢 Raw Logging (Debugging için çok değerli)
    print(f"📩 AI Raw Response:\n{raw_response}\n{'-'*30}")

    ai_results = {}
    if raw_response:
        for line in raw_response.split('\n'):
            if ':' in line:
                # 🟢 Güvenli Ayrıştırma (Strict Parsing)
                key, val = line.split(':', 1)
                key = key.strip().upper()
                
                # Sadece geçerli sipariş listesindeki hisseleri kabul et
                if key in valid_codes:
                    ai_results[key] = val.strip()
    
    # 🟢 Output Validation (Eksik Hisseleri Tamamlama)
    for o in safe_orders:
        if o['code'] not in ai_results or not ai_results[o['code']]:
            ai_results[o['code']] = "AI Eksik Yanıt (Timeout/Format Error)"
            
    return ai_results

# ================================
# MAIN ENGINE
# ================================
def main():
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS,BIMAS.IS")
    capital_input = float(os.getenv("PORTFOLIO_CAPITAL", START_CAPITAL))
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]

    ai_client = None
    if genai is not None and api_key:
        try: ai_client = genai.Client(api_key=api_key)
        except: pass

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
    if not selected_codes: return

    inv_vols = {c: 1/max(technicals[c]['volatility'], 0.01) for c in selected_codes}
    total_inv = sum(inv_vols.values())
    weights = {c: (iv / total_inv) for c, iv in inv_vols.items()} if total_inv > 0 else {c: 1/len(inv_vols) for c in inv_vols}

    target_portfolio = []
    for code in selected_codes:
        price = technicals[code]['price']
        lot = math.floor((capital_input * weights[code]) / price) if price > 0 else 0
        target_portfolio.append({"code": code, "price": price, "weight": weights[code], "lot": lot, "stop": max(0, safe_round(price - (technicals[code]['atr'] * 2.5)))})

    orders = []
    for item in target_portfolio:
        curr_lot = CURRENT_PORTFOLIO.get(item['code'], 0)
        if item['lot'] > curr_lot:
            orders.append({"type": "BUY", "code": item['code'], "lot": item['lot'] - curr_lot})

    for code, lot in CURRENT_PORTFOLIO.items():
        if code != "CASH" and not any(i['code'] == code for i in target_portfolio):
            orders.append({"type": "SELL", "code": code, "lot": lot})

    print("🚀 Toplu AI Yorumları İsteniyor...")
    ai_comments = get_batch_ai_commentary(ai_client, orders, technicals, fundamentals)

    md = f"## 🏦 Dr. Ömer - Apex Terminal v26.0 (Bulletproof Edition)\n**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
    md += "### ⚡ İŞLEM EMİRLERİ\n| İşlem | Hisse | Adet | AI Trader Onayı |\n| :--- | :--- | :--- | :--- |\n"

    for o in orders:
        ai_msg = ai_comments.get(o['code'], "Sistem Onaylı (AI Limit/Çevrimdışı)")
        md += f"| {'🟩 AL' if o['type']=='BUY' else '🟥 SAT'} | **{o['code']}** | {o['lot']} | {ai_msg} |\n"

    md += "\n---\n### 🎯 HEDEF PORTFÖY\n| Hisse | Ağırlık | Lot | İzleyen Stop |\n| :--- | :--- | :--- | :--- |\n"
    for r in target_portfolio:
        md += f"| **{r['code']}** | %{r['weight']*100:.1f} | {r['lot']} | {r['stop']} ₺ |\n"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f: f.write(md)

if __name__ == "__main__":
    main()
