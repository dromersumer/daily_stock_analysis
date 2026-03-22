# -*- coding: utf-8 -*-
import os, sys, json, math, time
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from google import genai
from json_repair import repair_json

# ================================
# CONFIG & STATE
# ================================
START_CAPITAL = 100000     
MAX_PORTFOLIO_SIZE = 5     
LOOKBACK_DAYS = 252        
FUNDAMENTAL_CACHE = {}     

CURRENT_PORTFOLIO = {
    "THYAO.IS": 50, "TUPRS.IS": 20, "CASH": 25000    
}

# ================================
# SAFE HELPERS
# ================================
def safe_float(x, default=0.0):
    try: return float(x)
    except: return default

def safe_div(a, b, default=0.0):
    try: return a / b if b not in [0, None] else default
    except: return default

def safe_round(x, n=2):
    try: return round(float(x), n) if pd.notna(x) else 0
    except: return 0

# ================================
# MACRO & TECHNICAL ENGINE
# ================================
def get_tcmb_inflation():
    try:
        api_key = os.getenv("EVDS_API_KEY")
        if not api_key: return 0.50
        url = f"https://evds2.tcmb.gov.tr/service/evds/series=TP.TUFE1&last=13&type=json&key={api_key}"
        res = requests.get(url, timeout=10)
        data = res.json()
        values = [safe_float(x.get('TP_TUFE1')) for x in (data.get('items') or []) if x.get('TP_TUFE1')]
        return safe_round((values[-1] / values[0]) - 1, 4) if len(values) >= 12 else 0.50
    except: return 0.50

def get_technical_and_regime(df):
    close = df['Close']
    df['ema200'] = close.ewm(span=200, adjust=False).mean()
    tr = pd.concat([df['High']-df['Low'], (df['High']-close.shift(1)).abs(), (df['Low']-close.shift(1)).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean().bfill()
    df['volatility'] = close.pct_change().rolling(20).std() * np.sqrt(LOOKBACK_DAYS)
    short_mom = close.pct_change(20).iloc[-1] if len(close) > 20 else 0
    
    last = df.iloc[-1]
    vol = safe_float(last['volatility'])
    if last['Close'] > last['ema200'] and short_mom > 0 and vol < 0.35: regime = "TREND_LOW_VOL"
    elif last['Close'] > last['ema200'] and short_mom > 0: regime = "TREND_HIGH_VOL"
    else: regime = "RANGE_OR_DOWN"

    return df, {"price": safe_round(last['Close']), "atr": safe_round(last['atr']), "volatility": safe_round(vol), "momentum": safe_round(last.pct_change(60)), "regime": regime}

# ================================
# FUNDAMENTAL ENGINE
# ================================
def get_fundamental(ticker_obj, code, current_inflation):
    clean_code = code.replace(".IS", "")
    try:
        res = requests.get(f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={clean_code}&exchange=TRY&financialGroup=XI_29&year1={datetime.now().year-1}&period1=12&year2={datetime.now().year-2}&period2=12", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        raw = res.json()['value']
        rev_curr = safe_float(next((i['value1'] for i in raw if i.get('itemDescTR') == 'SATIŞ GELİRLERİ'), 0))
        rev_prev = safe_float(next((i['value2'] for i in raw if i.get('itemDescTR') == 'SATIŞ GELİRLERİ'), 0))
        op_inc = safe_float(next((i['value1'] for i in raw) if 'ESAS FAALİYET KARI' in str(i.get('itemDescTR')) else 0), 0)
        leverage = safe_div(safe_float(next((i['value1'] for i in raw if 'YÜKÜMLÜLÜKLER' in str(i.get('itemDescTR'))), 0)), safe_float(next((i['value1'] for i in raw if 'ÖZKAYNAKLAR' in str(i.get('itemDescTR'))), 1)))
        nom_growth = (rev_curr / rev_prev - 1) * 100 if rev_prev > 0 else 0
        source = "ISYATIRIM"
    except:
        info = ticker_obj.info or {}
        nom_growth = (info.get("revenueGrowth", 0) or 0) * 100
        leverage = safe_div(safe_float(info.get("debtToEquity")), 100)
        source = "YFINANCE"

    real_growth = safe_div((1 + nom_growth/100), (1 + current_inflation)) - 1
    return {"source": source, "real_growth": safe_round(real_growth * 100), "leverage": safe_round(leverage), "peg": safe_float(ticker_obj.info.get("trailingPegRatio"))}

# ================================
# AI ENGINE (MODERN SDK)
# ================================
def ai_trade_desk_commentary(code, order, tech, fund, api_key):
    try:
        if not api_key: return "API Key Yok"
        client = genai.Client(api_key=api_key)
        
        # 🟢 LEVERAGE KEY ERROR FIX: get() kullanımı
        leverage = fund.get('leverage', 'Bilinmiyor')
        growth = fund.get('real_growth', 'Bilinmiyor')
        
        prompt = f"Trader yorumu yap. {code} için {order['type']} emri. Rejim: {tech.get('regime', 'Normal')}, Borç Oranı: {leverage}, Reel Büyüme: %{growth}. Tek cümlelik kurumsal onay ver."
        
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"🩺 DEBUG AI Error for {code}: {str(e)}")
        return "Sistem Onaylı (AI Çevrimdışı)"

# ================================
# MAIN
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
            if tech['regime'] != "RANGE_OR_DOWN": score += 40
            if fund['real_growth'] > 0: score += 40
            if fund['leverage'] < 1.5: score += 20
            
            technicals[code] = tech
            fundamentals[code] = fund # Artık tüm hisseleri saklıyoruz (KeyError FIX)
            if score > 30: 
                all_data[code] = df
                scores[code] = score
            time.sleep(1)

    selected_codes = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]
    if not selected_codes: return

    # Basit Risk Paritesi (Ters Volatilite)
    vols = {c: technicals[c]['volatility'] for c in selected_codes}
    inv_vols = {c: 1/v for c, v in vols.items()}
    weights = {c: iv / sum(inv_vols.values()) for c, iv in inv_vols.items()}

    target_portfolio = []
    for code in selected_codes:
        price = technicals[code]['price']
        lot = math.floor(safe_div(capital_input * weights[code], price))
        target_portfolio.append({"code": code, "price": price, "weight": weights[code], "lot": lot, "stop": max(0, safe_round(price - (technicals[code]['atr'] * 2.5)))})

    # Emir Üretimi
    orders = []
    for item in target_portfolio:
        curr_lot = CURRENT_PORTFOLIO.get(item['code'], 0)
        if item['lot'] > curr_lot: orders.append({"type": "BUY", "code": item['code'], "lot": item['lot'] - curr_lot})
    for code, lot in CURRENT_PORTFOLIO.items():
        if code != "CASH" and not any(i['code'] == code for i in target_portfolio):
            orders.append({"type": "SELL", "code": code, "lot": lot})

    md = f"## 🏦 Dr. Ömer - Apex Terminal v20.0\n**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
    md += "### ⚡ İŞLEM EMİRLERİ\n| İşlem | Hisse | Adet | AI Onayı |\n| :--- | :--- | :--- | :--- |\n"
    for o in orders:
        ai_msg = ai_trade_desk_commentary(o['code'], o, technicals.get(o['code'], {}), fundamentals.get(o['code'], {}), api_key)
        md += f"| {'🟩 AL' if o['type']=='BUY' else '🟥 SAT'} | **{o['code']}** | {o['lot']} | {ai_msg} |\n"
    
    md += "\n---\n### 🎯 HEDEF PORTFÖY\n| Hisse | Ağırlık | Lot | Stop |\n| :--- | :--- | :--- | :--- |\n"
    for r in target_portfolio:
        md += f"| **{r['code']}** | %{r['weight']*100:.1f} | {r['lot']} | {r['stop']} ₺ |\n"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f: f.write(md)

if __name__ == "__main__":
    main()
