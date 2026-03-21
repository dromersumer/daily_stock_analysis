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

# SANAL MEVCUT PORTFÖY (Execution Layer İçin Delta Hesaplama)
# Gerçek hayatta bu veri aracı kurum API'sinden (Örn: Info, Osmanlı) çekilir.
CURRENT_PORTFOLIO = {
    "THYAO.IS": 50,  # Elimde 50 lot var
    "TUPRS.IS": 20,
    "CASH": 25000    # Boşta bekleyen nakit
}

# ================================
# MACRO ENGINE
# ================================
def get_tcmb_inflation():
    try:
        api_key = os.getenv("EVDS_API_KEY")
        if not api_key: return 0.50
        url = f"https://evds2.tcmb.gov.tr/service/evds/series=TP.TUFE1&last=13&type=json&key={api_key}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            values = [float(x['TP_TUFE1']) for x in data['items'] if x.get('TP_TUFE1')]
            if len(values) >= 12: return round((values[-1] / values[0]) - 1, 4)
        return 0.50
    except: return 0.50

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
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))

    # ATR (Stop Loss için)
    prev_close = close.shift(1)
    tr = pd.concat([df['High'] - df['Low'], (df['High'] - prev_close).abs(), (df['Low'] - prev_close).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    returns = close.pct_change()
    df['volatility'] = returns.rolling(20).std() * np.sqrt(LOOKBACK_DAYS)
    
    # LEADING INDICATORS (Gecikmeyi Önlemek İçin)
    short_mom = close.pct_change(20).iloc[-1] # 1 Aylık Momentum
    df['momentum'] = close.pct_change(60)     # 3 Aylık Momentum

    last = df.iloc[-1]
    
    # LEADING REGIME DETECTION (Sadece EMA200 değil, kısa momentum da onaylamalı)
    if last['Close'] > last['ema200'] and short_mom > 0 and last['volatility'] < 0.35:
        regime = "TREND_LOW_VOL" 
    elif last['Close'] > last['ema200'] and short_mom > 0:
        regime = "TREND_HIGH_VOL"
    elif last['Close'] > last['ema200'] and short_mom < -0.05:
        regime = "WARNING_MOMENTUM_LOSS" # Trend dönüyor olabilir (Leading)
    else:
        regime = "RANGE_OR_DOWN" 

    return df, {
        "price": round(last['Close'], 2),
        "ema200": round(last['ema200'], 2),
        "rsi": round(last['rsi'], 2),
        "atr": round(last['atr'], 2),
        "volatility": round(last['volatility'], 2),
        "momentum": round(last['momentum'], 2),
        "regime": regime
    }

# ================================
# DATA LAYER: DEEP PARSING ENGINE
# ================================
def parse_deep_fundamentals(raw_data):
    """UPGRADED: Borçluluk (Leverage) ve Esas Faaliyet Karı (EBITDA Proxy) eklendi"""
    try:
        # Gelir Tablosu
        rev_curr = next((float(i['value1']) for i in raw_data if i.get('itemDescTR') == 'SATIŞ GELİRLERİ'), 0)
        rev_prev = next((float(i['value2']) for i in raw_data if i.get('itemDescTR') == 'SATIŞ GELİRLERİ'), 0)
        net_inc = next((float(i['value1']) for i in raw_data if i.get('itemDescTR') == 'DÖNEM KARI (ZARARI)'), 0)
        op_inc = next((float(i['value1']) for i in raw_data if i.get('itemDescTR') == 'ESAS FAALİYET KARI (ZARARI)'), 0)
        
        # Bilanço (Borç & Kaldıraç)
        short_debt = next((float(i['value1']) for i in raw_data if i.get('itemDescTR') == 'KISA VADELİ YÜKÜMLÜLÜKLER'), 0)
        long_debt = next((float(i['value1']) for i in raw_data if i.get('itemDescTR') == 'UZUN VADELİ YÜKÜMLÜLÜKLER'), 0)
        equity = next((float(i['value1']) for i in raw_data if i.get('itemDescTR') == 'ÖZKAYNAKLAR'), 1) # Div/0 koruması
        
        nom_growth = (rev_curr / rev_prev - 1) * 100 if rev_prev > 0 else 0
        op_margin = (op_inc / rev_curr) * 100 if rev_curr > 0 else 0
        leverage = (short_debt + long_debt) / equity # Borç / Özkaynak Oranı
        
        return nom_growth, op_margin, leverage
    except: return 0, 0, 0

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
    
    if is_data["status"] == "success":
        source = "ISYATIRIM"
        nom_growth, op_margin, leverage = parse_deep_fundamentals(is_data["raw_data"])
        peg = ticker_obj.info.get("trailingPegRatio", None)
    else:
        source = "YFINANCE"
        info = ticker_obj.info
        nom_growth = (info.get("revenueGrowth", 0) or 0) * 100
        op_margin = (info.get("operatingMargins", 0) or 0) * 100
        leverage = info.get("debtToEquity", 0) / 100 if info.get("debtToEquity") else 0
        peg = info.get("trailingPegRatio", None)

    real_growth = ((1 + nom_growth/100) / (1 + current_inflation)) - 1

    return {
        "source": source,
        "real_growth": round(real_growth * 100, 2),
        "op_margin": round(op_margin, 2),
        "leverage": round(leverage, 2), # Borçluluk (0.5 altı iyi, 2 üstü riskli)
        "peg": round(peg, 2) if peg is not None else None
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
    else: w_mom, w_vol, w_growth, w_margin = 0, 50, 0, 50 # Defansif Mod
        
    if tech['momentum'] > 0: score += w_mom
    if tech['volatility'] < 0.35: score += w_vol
    if fund['real_growth'] > 5: score += w_growth
    if fund['op_margin'] > 15: score += w_margin
    
    # BORÇ CEZASI (Execution katmanı risk istemez)
    if fund['leverage'] > 2.0: score -= 20
    elif fund['leverage'] < 0.5: score += 10
    
    if fund['peg'] and fund['peg'] < 1.5: score += 10
    return round(score, 1)

# ================================
# COVARIANCE RISK PARITY (CORRELATION PENALTY)
# ================================
def calculate_covariance_parity(selected_stocks_data):
    returns_df = pd.DataFrame({code: data['Close'].pct_change() for code, data in selected_stocks_data.items()}).dropna()
    cov_matrix = returns_df.cov()
    
    # Gerçek Risk Paritesine daha yakın Marginal Risk Contribution tahmini
    inv_cov_sum = 1 / cov_matrix.sum(axis=1)
    if inv_cov_sum.sum() == 0: return {code: 1.0/len(selected_stocks_data) for code in selected_stocks_data}
    weights = inv_cov_sum / inv_cov_sum.sum()
    return weights.to_dict()

# ================================
# THE EXECUTION LAYER (AL/SAT EMİRLERİ)
# ================================
def generate_trade_orders(target_portfolio, current_portfolio, capital):
    """Hedef portföy ile mevcut portföyü kıyaslayıp Gerçek Emirler (Trade Orders) üretir"""
    orders = []
    
    # Mevcut portföydeki hisselerin değerini hesapla
    current_value = current_portfolio.get("CASH", 0)
    for code, lot in current_portfolio.items():
        if code == "CASH": continue
        # Basitlik için hedefte varsa fiyatını oradan alıyoruz
        target_item = next((item for item in target_portfolio if item['code'] == code), None)
        if target_item: current_value += lot * target_item['price']
    
    # Gerçek Fon Büyüklüğü
    total_capital = max(capital, current_value)

    # 1. SATIŞ EMİRLERİ (Portföyden çıkanlar veya azaltılması gerekenler)
    for code, current_lot in current_portfolio.items():
        if code == "CASH": continue
        target_item = next((item for item in target_portfolio if item['code'] == code), None)
        
        if not target_item:
            orders.append({"type": "SELL", "code": code, "lot": current_lot, "reason": "Sistemden Çıktı (Rejim/Skor Kötü)"})
        else:
            target_lot = target_item['lot']
            if current_lot > target_lot:
                orders.append({"type": "SELL", "code": code, "lot": current_lot - target_lot, "reason": "Ağırlık Azaltma (Rebalance)"})

    # 2. ALIŞ EMİRLERİ (Yeni girenler veya artırılması gerekenler)
    for item in target_portfolio:
        code = item['code']
        target_lot = item['lot']
        current_lot = current_portfolio.get(code, 0)
        
        if current_lot < target_lot:
            orders.append({"type": "BUY", "code": code, "lot": target_lot - current_lot, "reason": "Ağırlık Artırma / Yeni Giriş"})

    return orders

# ================================
# AI COMMENTARY (TRADE DESK)
# ================================
def ai_trade_desk_commentary(code, order, tech, fund, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""
        Baş Trader'sın. Sistem {code} hissesi için şu emri üretti: {order['type']} {order['lot']} LOT.
        Gerekçe: {order['reason']}
        VERİLER: Rejim: {tech['regime']} | Kaldıraç (Borç): {fund['leverage']} | Reel Büyüme: %{fund['real_growth']}
        
        GÖREV: Bu emri mantıksal olarak doğrula. Borçluluk ve rejim verilerini kullanarak bu "Execution" hamlesinin neden doğru olduğunu tek cümleyle açıkla.
        """
        return model.generate_content(prompt).text.strip()
    except: return "-"

# ================================
# MAIN ENGINE
# ================================
def main():
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS,BIMAS.IS")
    capital_input = float(os.getenv("PORTFOLIO_CAPITAL", START_CAPITAL))
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    
    print("🚀 Apex Execution Engine (v11.0) Başlatılıyor...")
    current_inflation = get_tcmb_inflation()

    all_data, scores, fundamentals, technicals = {}, {}, {}, {}

    for code in stock_codes:
        ticker = yf.Ticker(code)
        df = ticker.history(period="2y")
        
        if not df.empty and len(df) > 200:
            df, tech = get_technical_and_regime(df)
            fund = get_fundamental(ticker, code, current_inflation)
            score = dynamic_factor_score(tech, fund)
            
            # Ayı Piyasasında Katı Filtre
            if score > 30: 
                all_data[code] = df
                scores[code] = score
                fundamentals[code] = fund
                technicals[code] = tech
            time.sleep(2) 
            
    selected_codes = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]
    selected_data = {code: all_data[code] for code in selected_codes}
    
    weights = calculate_covariance_parity(selected_data)
    target_portfolio = []
    
    # 1. HEDEF PORTFÖYÜ İNŞA ET VE STOPLARI BELİRLE
    for code in selected_codes:
        weight = weights[code]
        allocated = capital_input * weight
        price = technicals[code]['price']
        lot = math.floor(allocated / price) if price > 0 else 0
        stop_loss = round(price - (technicals[code]['atr'] * 2.5), 2) # 2.5 ATR İzleyen Stop
        
        target_portfolio.append({
            "code": code, "price": price, "weight": weight, "lot": lot, 
            "stop": stop_loss, "regime": technicals[code]['regime']
        })

    # 2. EXECUTION LAYER: EMİRLERİ ÜRET (Delta hesapla)
    trade_orders = generate_trade_orders(target_portfolio, CURRENT_PORTFOLIO, capital_input)

    md = "<small>\n\n## 🏦 Dr. Ömer - Apex Execution Desk (v11.0)\n\n"
    md += f"**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')} | **Model:** Macro-Quant + Active Rebalancing\n\n"
    
    # --- YENİ BÖLÜM: TRADE ORDERS (İŞLEM EMRİ) ---
    md += "### ⚡ AKTİF İŞLEM EMİRLERİ (EXECUTION LAYER)\n"
    if not trade_orders:
        md += "> *Mevcut portföy optimal. Rebalancing (İşlem) gerekmiyor.*\n\n"
    else:
        md += "| İşlem | Hisse | Adet | Sistem Gerekçesi | Trader (AI) Onayı |\n"
        md += "| :--- | :--- | :--- | :--- | :--- |\n"
        for order in trade_orders:
            code = order['code']
            tech = technicals.get(code, {"regime": "Sistem Dışı"})
            fund = fundamentals.get(code, {"leverage": "Bilinmiyor", "real_growth": "Bilinmiyor"})
            
            icon = "🟩 AL" if order['type'] == "BUY" else "🟥 SAT"
            ai_comment = ai_trade_desk_commentary(code, order, tech, fund, api_key)
            md += f"| **{icon}** | **{code}** | {order['lot']} | {order['reason']} | {ai_comment} |\n"
            time.sleep(4)

    # --- HEDEF PORTFÖY VE RİSK YÖNETİMİ ---
    md += "\n---\n### 🎯 GÜNCEL HEDEF PORTFÖY VE RİSK YÖNETİMİ\n"
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
