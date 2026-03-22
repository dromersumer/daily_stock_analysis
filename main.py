# -*- coding: utf-8 -*-
import os, sys, json, math, time, smtplib
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import google.generativeai as genai
from json_repair import repair_json
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ================================
# CONFIG, CACHE & EXECUTION STATE
# ================================
START_CAPITAL = 100000     
MAX_PORTFOLIO_SIZE = 5     
LOOKBACK_DAYS = 252        
FUNDAMENTAL_CACHE = {}     

CURRENT_PORTFOLIO = {
    "THYAO.IS": 50,  
    "TUPRS.IS": 20,
    "CASH": 25000    
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
    try:
        if pd.isna(x): return 0
        return round(x, n)
    except: return 0

# ================================
# MACRO ENGINE
# ================================
def get_tcmb_inflation():
    try:
        api_key = os.getenv("EVDS_API_KEY")
        if not api_key: return 0.50
        url = f"https://evds2.tcmb.gov.tr/service/evds/series=TP.TUFE1&last=13&type=json&key={api_key}"
        res = requests.get(url, timeout=10)
        if res.status_code != 200: return 0.50
        data = res.json()
        items = data.get('items') or data.get('data') or []
        values = [safe_float(x.get('TP_TUFE1')) for x in items if x.get('TP_TUFE1')]
        if len(values) < 12: return 0.50
        return safe_round((values[-1] / values[0]) - 1, 4)
    except: return 0.50

# ================================
# TECHNICAL & REGIME
# ================================
def get_technical_and_regime(df):
    close = df['Close']
    df['ema200'] = close.ewm(span=200, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    tr = pd.concat([df['High'] - df['Low'], (df['High'] - close.shift(1)).abs(), (df['Low'] - close.shift(1)).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean().bfill()
    df['volatility'] = close.pct_change().rolling(20).std() * np.sqrt(LOOKBACK_DAYS)
    short_mom = close.pct_change(20).iloc[-1] if len(close) > 20 else 0
    df['momentum'] = close.pct_change(60)

    last = df.iloc[-1]
    vol = safe_float(last['volatility'])
    if last['Close'] > last['ema200'] and short_mom > 0 and vol < 0.35: regime = "TREND_LOW_VOL" 
    elif last['Close'] > last['ema200'] and short_mom > 0: regime = "TREND_HIGH_VOL"
    elif last['Close'] > last['ema200'] and short_mom < -0.05: regime = "WARNING_MOMENTUM_LOSS" 
    else: regime = "RANGE_OR_DOWN" 

    return df, {
        "price": safe_round(last['Close']), "rsi": safe_round(last['rsi']),
        "atr": safe_round(last['atr']), "volatility": safe_round(vol),
        "momentum": safe_round(last['momentum']), "regime": regime
    }

# ================================
# FUNDAMENTAL PARSER
# ================================
def parse_deep_fundamentals(raw_data):
    try:
        rev_curr = safe_float(next((i['value1'] for i in raw_data if i.get('itemDescTR') == 'SATIŞ GELİRLERİ'), 0))
        rev_prev = safe_float(next((i['value2'] for i in raw_data if i.get('itemDescTR') == 'SATIŞ GELİRLERİ'), 0))
        net_inc = safe_float(next((i['value1'] for i in raw_data if i.get('itemDescTR') == 'DÖNEM KARI (ZARARI)'), 0))
        op_inc = safe_float(next((i['value1'] for i in raw_data if i.get('itemDescTR') == 'ESAS FAALİYET KARI (ZARARI)'), 0))
        short_debt = safe_float(next((i['value1'] for i in raw_data if i.get('itemDescTR') == 'KISA VADELİ YÜKÜMLÜLÜKLER'), 0))
        long_debt = safe_float(next((i['value1'] for i in raw_data if i.get('itemDescTR') == 'UZUN VADELİ YÜKÜMLÜLÜKLER'), 0))
        equity = safe_float(next((i['value1'] for i in raw_data if i.get('itemDescTR') == 'ÖZKAYNAKLAR'), 1))
        return (rev_curr / rev_prev - 1) * 100, (op_inc / rev_curr) * 100, (short_debt + long_debt) / equity
    except: return 0, 0, 0

def get_fundamental(ticker_obj, code, current_inflation):
    clean_code = code.replace(".IS", "")
    url = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
    params = {"companyCode": clean_code, "exchange": "TRY", "financialGroup": "XI_29", "year1": datetime.now().year - 1, "period1": 12, "year2": datetime.now().year - 2, "period2": 12}
    try:
        res = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        nom_growth, op_margin, leverage = parse_deep_fundamentals(res.json()['value'])
        source = "ISYATIRIM"
    except:
        info = ticker_obj.info or {}
        nom_growth = (info.get("revenueGrowth", 0) or 0) * 100
        op_margin = (info.get("operatingMargins", 0) or 0) * 100
        leverage = safe_div(safe_float(info.get("debtToEquity")), 100)
        source = "YFINANCE"

    real_growth = safe_div((1 + nom_growth/100), (1 + current_inflation)) - 1
    return {"source": source, "real_growth": safe_round(real_growth * 100), "op_margin": safe_round(op_margin), "leverage": safe_round(leverage), "peg": safe_float(ticker_obj.info.get("trailingPegRatio"))}

# ================================
# SCORING & COVARIANCE
# ================================
def dynamic_factor_score(tech, fund):
    score = 0
    if tech['momentum'] > 0: score += 20
    if tech['volatility'] < 0.35: score += 20
    if fund['real_growth'] > 5: score += 20
    if fund['op_margin'] > 15: score += 20
    if fund['leverage'] < 1.0: score += 10
    if fund['peg'] and 0 < fund['peg'] < 1.5: score += 10
    return safe_round(score, 1)

def calculate_covariance_parity(selected_stocks_data):
    if len(selected_stocks_data) <= 1: return {list(selected_stocks_data.keys())[0]: 1.0} if selected_stocks_data else {}
    returns_df = pd.DataFrame({code: data['Close'].pct_change() for code, data in selected_stocks_data.items()}).dropna()
    if returns_df.empty: return {code: 1.0/len(selected_stocks_data) for code in selected_stocks_data}
    inv_vol = 1 / returns_df.std()
    weights = inv_vol / inv_vol.sum()
    return weights.to_dict()

# ================================
# EXECUTION LAYER
# ================================
def generate_trade_orders(target_portfolio, current_portfolio, capital, technicals):
    orders = []
    current_value = current_portfolio.get("CASH", 0)
    for code, lot in current_portfolio.items():
        if code == "CASH": continue
        try:
            price = next((item['price'] for item in target_portfolio if item['code'] == code), technicals.get(code, {}).get('price', 0))
            if price == 0: price = safe_float(yf.Ticker(code).history(period="5d")['Close'].iloc[-1])
        except: price = 0
        current_value += lot * price
    
    for item in target_portfolio:
        curr_lot = current_portfolio.get(item['code'], 0)
        if item['lot'] > curr_lot: orders.append({"type": "BUY", "code": item['code'], "lot": item['lot'] - curr_lot, "reason": "Ağırlık Artırma"})
    for code, lot in current_portfolio.items():
        if code != "CASH" and not any(i['code'] == code for i in target_portfolio):
            orders.append({"type": "SELL", "code": code, "lot": lot, "reason": "Sistem Dışı"})
    return orders

# ================================
# AI TRADE DESK (UPGRADED DEBUG)
# ================================
def ai_trade_desk_commentary(code, order, tech, fund, api_key):
    try:
        if not api_key: return "API Key Bulunamadı"
        genai.configure(api_key=api_key)
        
        # GÜVENLİK AYARLARINI ESNETİYORUZ (Safety Bypass)
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        # MODEL ADI GÜNCELLEMESİ
        model = genai.GenerativeModel(model_name="models/gemini-1.5-flash", safety_settings=safety_settings)
        
        prompt = f"{code} için {order['type']} emri verildi. Rejim: {tech['regime']}, Kaldıraç: {fund['leverage']}, Reel Büyüme: %{fund['real_growth']}. Bu hamleyi trader gözüyle tek cümleyle onayla."
        
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        # 🩺 BURASI KRİTİK: Hatayı GitHub Loglarına Yazdırıyoruz
        print(f"🩺 DEBUG AI Error for {code}: {str(e)}")
        return "Sistem Onaylı (AI Çevrimdışı)"

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
            score = dynamic_factor_score(tech, fund)
            technicals[code] = tech
            if score > 30: 
                all_data[code] = df
                scores[code] = score
                fundamentals[code] = fund
            time.sleep(1)

    selected_codes = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]
    if not selected_codes: return

    weights = calculate_covariance_parity({c: all_data[c] for c in selected_codes})
    target_portfolio = []
    for code in selected_codes:
        w = weights.get(code, 0)
        price = technicals[code]['price']
        lot = math.floor(safe_div(capital_input * w, price))
        target_portfolio.append({"code": code, "price": price, "weight": w, "lot": lot, "stop": max(0, safe_round(price - (technicals[code]['atr'] * 2.5))), "regime": technicals[code]['regime']})

    trade_orders = generate_trade_orders(target_portfolio, CURRENT_PORTFOLIO, capital_input, technicals)

    md = f"## 🏦 Dr. Ömer - Apex Terminal v19.0\n**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
    md += "### ⚡ İŞLEM EMİRLERİ\n| İşlem | Hisse | Adet | AI Onayı |\n| :--- | :--- | :--- | :--- |\n"
    for o in trade_orders:
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
