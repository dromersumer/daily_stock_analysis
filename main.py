# -*- coding: utf-8 -*-
import os, sys, json, math, time, smtplib
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import google.generativeai as genai
from json_repair import repair_json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
# SAFE HELPERS (PRODUCTION ZIRHI)
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
# MACRO ENGINE (EVDS SAFE)
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
    except Exception as e:
        print(f"[EVDS ERROR] {e}")
        return 0.50

# ================================
# TECHNICAL & LEADING REGIME ENGINE
# ================================
def get_technical_and_regime(df):
    close = df['Close']
    df['ema21'] = close.ewm(span=21, adjust=False).mean()
    df['ema50'] = close.ewm(span=50, adjust=False).mean()
    df['ema200'] = close.ewm(span=200, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    prev_close = close.shift(1)
    tr = pd.concat([df['High'] - df['Low'], (df['High'] - prev_close).abs(), (df['Low'] - prev_close).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean().bfill()

    returns = close.pct_change()
    df['volatility'] = returns.rolling(20).std() * np.sqrt(LOOKBACK_DAYS)
    
    short_mom = close.pct_change(20).iloc[-1] if len(close) > 20 else 0
    df['momentum'] = close.pct_change(60)

    last = df.iloc[-1]
    vol = safe_float(last['volatility'])
    mom = safe_float(last['momentum'])
    
    if last['Close'] > last['ema200'] and short_mom > 0 and vol < 0.35: regime = "TREND_LOW_VOL" 
    elif last['Close'] > last['ema200'] and short_mom > 0: regime = "TREND_HIGH_VOL"
    elif last['Close'] > last['ema200'] and short_mom < -0.05: regime = "WARNING_MOMENTUM_LOSS" 
    else: regime = "RANGE_OR_DOWN" 

    return df, {
        "price": safe_round(last['Close']),
        "ema200": safe_round(last['ema200']),
        "rsi": safe_round(last['rsi']),
        "atr": safe_round(last['atr']),
        "volatility": safe_round(vol),
        "momentum": safe_round(mom),
        "regime": regime
    }

# ================================
# FUNDAMENTAL PARSER (DEEP ANALYSIS)
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
        
        nom_growth = safe_div(rev_curr, rev_prev, 1) - 1
        op_margin = safe_div(op_inc, rev_curr)
        leverage = safe_div((short_debt + long_debt), equity)
        
        return nom_growth * 100, op_margin * 100, leverage
    except Exception as e:
        print(f"[FUND PARSE ERROR] {e}")
        return 0, 0, 0

def get_isyatirim_data(clean_code):
    if clean_code in FUNDAMENTAL_CACHE: return FUNDAMENTAL_CACHE[clean_code]
    url = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
    params = {"companyCode": clean_code, "exchange": "TRY", "financialGroup": "XI_29", "year1": datetime.now().year - 1, "period1": 12, "year2": datetime.now().year - 2, "period2": 12}
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if 'value' in data and len(data['value']) > 0:
                FUNDAMENTAL_CACHE[clean_code] = {"status": "success", "raw_data": data['value']}
                return FUNDAMENTAL_CACHE[clean_code]
    except: pass
    return {"status": "error"}

def get_fundamental(ticker_obj, code, current_inflation):
    clean_code = code.replace(".IS", "")
    is_data = get_isyatirim_data(clean_code)
    
    info = ticker_obj.info or {}
    
    if is_data["status"] == "success":
        source = "ISYATIRIM"
        nom_growth, op_margin, leverage = parse_deep_fundamentals(is_data["raw_data"])
        peg = info.get("trailingPegRatio", None)
    else:
        source = "YFINANCE"
        nom_growth = (info.get("revenueGrowth", 0) or 0) * 100
        op_margin = (info.get("operatingMargins", 0) or 0) * 100
        leverage = safe_div(safe_float(info.get("debtToEquity")), 100)
        peg = info.get("trailingPegRatio", None)

    real_growth = safe_div((1 + nom_growth/100), (1 + current_inflation)) - 1

    return {
        "source": source,
        "real_growth": safe_round(real_growth * 100),
        "op_margin": safe_round(op_margin),
        "leverage": safe_round(leverage),
        "peg": safe_float(peg) if peg is not None else None
    }

# ================================
# REGIME-SWITCHING & DEBT PENALTY
# ================================
def dynamic_factor_score(tech, fund):
    regime = tech['regime']
    score = 0
    
    if regime == "TREND_LOW_VOL": w_mom, w_vol, w_growth, w_margin = 25, 15, 30, 20
    elif regime == "TREND_HIGH_VOL": w_mom, w_vol, w_growth, w_margin = 15, 25, 20, 30
    elif regime == "WARNING_MOMENTUM_LOSS": w_mom, w_vol, w_growth, w_margin = 0, 40, 10, 40
    else: w_mom, w_vol, w_growth, w_margin = 0, 50, 0, 50 
        
    if tech['momentum'] > 0: score += w_mom
    if tech['volatility'] < 0.35: score += w_vol
    if fund['real_growth'] > 5: score += w_growth
    if fund['op_margin'] > 15: score += w_margin
    
    if fund['leverage'] > 2.0: score -= 20
    elif fund['leverage'] < 0.5: score += 10
    
    if fund['peg'] is not None and fund['peg'] > 0 and fund['peg'] < 1.5: 
        score += 10
        
    return safe_round(score, 1)

# ================================
# COVARIANCE RISK PARITY
# ================================
def calculate_covariance_parity(selected_stocks_data):
    if not selected_stocks_data: return {}
    
    if len(selected_stocks_data) == 1:
        return {list(selected_stocks_data.keys())[0]: 1.0}

    returns_df = pd.DataFrame({code: data['Close'].pct_change() for code, data in selected_stocks_data.items()}).dropna()
    
    if returns_df.empty or len(returns_df.columns) == 0:
        return {code: 1.0/len(selected_stocks_data) for code in selected_stocks_data}
        
    cov_matrix = returns_df.cov()
    row_sums = cov_matrix.sum(axis=1).replace(0, np.nan)
    inv_cov_sum = 1 / row_sums
    
    if inv_cov_sum.isna().all():
        return {code: 1.0/len(selected_stocks_data) for code in selected_stocks_data}
        
    weights = inv_cov_sum / inv_cov_sum.sum()
    return weights.fillna(0).to_dict()

# ================================
# THE EXECUTION LAYER (IMMORTAL DATA FALLBACK)
# ================================
def generate_trade_orders(target_portfolio, current_portfolio, capital, technicals):
    orders = []
    current_value = current_portfolio.get("CASH", 0)
    
    for code, lot in current_portfolio.items():
        if code == "CASH": continue
        target_item = next((item for item in target_portfolio if item['code'] == code), None)
        
        if target_item:
            price = target_item['price']
        elif code in technicals and 'price' in technicals[code]:
            price = technicals[code]['price']
        else:
            try:
                tkr = yf.Ticker(code)
                hist = tkr.history(period="1mo")
                if not hist.empty:
                    price = safe_float(hist['Close'].iloc[-1])
                else:
                    f_info = getattr(tkr, 'fast_info', None)
                    if f_info is not None:
                        p_val = getattr(f_info, 'last_price', None)
                        if p_val is None and hasattr(f_info, 'get'):
                            p_val = f_info.get('last_price', 0)
                        price = safe_float(p_val)
                    else:
                        price = 0
            except Exception as e:
                print(f"⚠️ {code} anlık fiyatı hiçbir şekilde bulunamadı. Tahta kapalı olabilir. Hata: {e}")
                price = 0
                
        current_value += lot * price
    
    total_capital = max(capital, current_value)

    for code, current_lot in current_portfolio.items():
        if code == "CASH": continue
        target_item = next((item for item in target_portfolio if item['code'] == code), None)
        if not target_item:
            orders.append({"type": "SELL", "code": code, "lot": current_lot, "reason": "Sistem Dışı (Rejim/Skor Kötü)"})
        else:
            target_lot = target_item['lot']
            if current_lot > target_lot:
                orders.append({"type": "SELL", "code": code, "lot": current_lot - target_lot, "reason": "Rebalance (Ağırlık Azaltma)"})

    for item in target_portfolio:
        code = item['code']
        target_lot = item['lot']
        current_lot = current_portfolio.get(code, 0)
        
        if target_lot > 0 and current_lot < target_lot:
            orders.append({"type": "BUY", "code": code, "lot": target_lot - current_lot, "reason": "Rebalance / Yeni Giriş"})

    return orders

# ================================
# AI TRADE DESK
# ================================
def ai_trade_desk_commentary(code, order, tech, fund, api_key):
    try:
        if not api_key: return "Sistem Onaylı (API Key Yok)"
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Baş Trader'sın. Sistem {code} hissesi için şu emri üretti: {order['type']} {order['lot']} LOT. Gerekçe: {order['reason']}. VERİLER: Rejim: {tech['regime']} | Kaldıraç: {fund['leverage']} | Reel Büyüme: %{fund['real_growth']}. GÖREV: Bu emri mantıksal olarak tek cümleyle doğrula."
        return model.generate_content(prompt).text.strip()
    except: return "Sistem Onaylı (AI Çevrimdışı)"

# ================================
# MAIN ENGINE
# ================================
def main():
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS,BIMAS.IS")
    capital_input = float(os.getenv("PORTFOLIO_CAPITAL", START_CAPITAL))
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    
    print("🚀 Niteliksel Mimari Başlatılıyor (Production Grade v18.0)...")
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
    
    if not selected_codes:
        print("⚠️ Uygun hisse bulunamadı (Tümü RANGE_OR_DOWN rejiminde veya skorları yetersiz).")
        return

    selected_data = {code: all_data[code] for code in selected_codes}
    weights = calculate_covariance_parity(selected_data)
    target_portfolio = []
    
    for code in selected_codes:
        weight = weights.get(code, 0)
        allocated = capital_input * weight
        price = technicals[code]['price']
        
        lot = math.floor(safe_div(allocated, price)) if price > 0 else 0
        
        if lot == 0:
            print(f"⚠️ {code}: Ayrılan bütçe ({allocated:.2f} TL), 1 lot almak için yetersiz. Hedef 0 lot.")
            
        stop_loss = max(0, safe_round(price - (technicals[code]['atr'] * 2.5))) 
        
        target_portfolio.append({
            "code": code, "price": price, "weight": weight, "lot": lot, 
            "stop": stop_loss, "regime": technicals[code]['regime']
        })

    trade_orders = generate_trade_orders(target_portfolio, CURRENT_PORTFOLIO, capital_input, technicals)

    md = "<small>\n\n## 🏦 Dr. Ömer - Institutional Quant Terminal (v18.0)\n\n"
    md += f"**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')} | **Model:** 100% Production-Safe / Zero-Latency\n\n"
    
    md += "### ⚡ AKTİF İŞLEM EMİRLERİ (EXECUTION LAYER)\n"
    if not trade_orders:
        md += "> *Mevcut portföy optimal. Rebalancing gerekmiyor.*\n\n"
    else:
        md += "| İşlem | Hisse | Adet | Sistem Gerekçesi | Trader (AI) Onayı |\n"
        md += "| :--- | :--- | :--- | :--- | :--- |\n"
        for order in trade_orders:
            code = order['code']
            tech = technicals.get(code, {"regime": "Sistem Dışı"})
            fund = fundamentals.get(code, {"leverage": 0, "real_growth": 0})
            
            icon = "🟩 AL" if order['type'] == "BUY" else "🟥 SAT"
            ai_comment = ai_trade_desk_commentary(code, order, tech, fund, api_key)
            md += f"| **{icon}** | **{code}** | {order['lot']} | {order['reason']} | {ai_comment} |\n"
            time.sleep(2)

    md += "\n---\n### 🎯 HEDEF PORTFÖY VE RİSK YÖNETİMİ\n"
    md += "| Hisse | Rejim (Öncü) | Hedef Ağırlık | Taşınacak Lot | İzleyen Stop (2.5 ATR) |\n"
    md += "| :--- | :--- | :--- | :--- | :--- |\n"
    
    for r in target_portfolio:
        regime_icon = "🟢" if "LOW_VOL" in r['regime'] else ("⚠️" if "WARNING" in r['regime'] else "🟡")
        md += f"| **{r['code']}** | {regime_icon} {r['regime']} | **%{r['weight']*100:.1f}** | **{r['lot']}** | **{r['stop']} ₺** |\n"
    
    md += "</small>"
    
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f: f.write(md)

if __name__ == "__main__":
    main()
