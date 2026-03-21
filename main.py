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
# CONFIG & CACHE
# ================================
START_CAPITAL = 100000     
MAX_PORTFOLIO_SIZE = 5     
LOOKBACK_DAYS = 252        
FUNDAMENTAL_CACHE = {}     

# ================================
# MACRO ENGINE (TCMB EVDS)
# ================================
def get_tcmb_inflation():
    """TCMB EVDS API'den Son 1 Yıllık (YoY) Gerçek Enflasyonu Çeker"""
    try:
        api_key = os.getenv("EVDS_API_KEY")
        if not api_key:
            print("⚠️ EVDS API Key bulunamadı. Fallback (%50) kullanılıyor.")
            return 0.50

        url = f"https://evds2.tcmb.gov.tr/service/evds/series=TP.TUFE1&last=13&type=json&key={api_key}"
        res = requests.get(url, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            # None veya boş gelen verileri filtreleyip float'a çeviriyoruz
            values = [float(x['TP_TUFE1']) for x in data['items'] if x.get('TP_TUFE1')]
            
            if len(values) >= 12:
                # Son ay / 12 Ay Önceki Ay (YoY Enflasyon Formülü)
                inflation = (values[-1] / values[0]) - 1
                return round(inflation, 4)
                
        print("⚠️ EVDS Verisi eksik veya hatalı. Fallback (%50) kullanılıyor.")
        return 0.50
    except Exception as e:
        print(f"⚠️ EVDS API Bağlantı Hatası ({e}). Fallback (%50) kullanılıyor.")
        return 0.50

# ================================
# TECHNICAL & REGIME ENGINE
# ================================
def get_technical_and_regime(df):
    close = df['Close']
    df['ema21'] = close.ewm(span=21, adjust=False).mean()
    df['ema50'] = close.ewm(span=50, adjust=False).mean()
    df['ema200'] = close.ewm(span=200, adjust=False).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))

    # Volatility & Momentum
    returns = close.pct_change()
    df['volatility'] = returns.rolling(20).std() * np.sqrt(LOOKBACK_DAYS)
    df['momentum'] = close.pct_change(60)

    last = df.iloc[-1]
    regime = "RANGE_OR_DOWN"
    if last['Close'] > last['ema200'] and last['volatility'] < 0.35:
        regime = "TREND_LOW_VOL" 
    elif last['Close'] > last['ema200']:
        regime = "TREND_HIGH_VOL" 

    return df, {
        "price": round(last['Close'], 2),
        "ema200": round(last['ema200'], 2),
        "rsi": round(last['rsi'], 2),
        "volatility": round(last['volatility'], 2),
        "momentum": round(last['momentum'], 2),
        "regime": regime
    }

# ================================
# DATA LAYER: HYBRID FUNDAMENTAL ENGINE
# ================================
def get_isyatirim_data(clean_code):
    if clean_code in FUNDAMENTAL_CACHE: return FUNDAMENTAL_CACHE[clean_code]
        
    url = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
    params = {"companyCode": clean_code, "exchange": "TRY", "financialGroup": "XI_29", "year1": datetime.now().year - 1, "period1": 12, "year2": datetime.now().year - 2, "period2": 12}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept': 'application/json'}
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if 'value' in data and len(data['value']) > 0:
                FUNDAMENTAL_CACHE[clean_code] = {"status": "success", "raw_data": data['value']}
                return FUNDAMENTAL_CACHE[clean_code]
    except Exception as e:
        print(f"⚠️ İş Yatırım API Hatası ({clean_code}): {e}")
        
    return {"status": "error"}

def get_fundamental(ticker_obj, code, current_inflation):
    clean_code = code.replace(".IS", "")
    is_data = get_isyatirim_data(clean_code)
    
    source = "ISYATIRIM" if is_data["status"] == "success" else "YFINANCE (Fallback)"

    try:
        info = ticker_obj.info
        rev_growth = (info.get("revenueGrowth", 0) or 0) * 100
        margin = (info.get("profitMargins", 0) or 0) * 100
        peg = info.get("trailingPegRatio", None)

        # SİZİN YAZDIĞINIZ DİNAMİK FISHER DENKLEMİ (Canlı Enflasyon ile)
        real_growth = ((1 + rev_growth/100) / (1 + current_inflation)) - 1

        return {
            "source": source,
            "real_growth": round(real_growth * 100, 2),
            "margin": round(margin, 2),
            "peg": round(peg, 2) if peg is not None else None
        }
    except:
        return {"source": "ERROR", "real_growth": 0, "margin": 0, "peg": None}

# ================================
# MULTI-FACTOR SCORING ENGINE
# ================================
def factor_score(tech, fund):
    score = 0
    if tech['momentum'] > 0: score += 15
    if tech['momentum'] > 0.1: score += 10 
    if tech['price'] > tech['ema200']: score += 15
    if tech['volatility'] < 0.35: score += 10
    if tech['regime'] == "TREND_LOW_VOL": score += 10
    if fund['real_growth'] > 10: score += 20
    if fund['margin'] > 15: score += 10
    if fund['peg'] and fund['peg'] < 1.5: score += 10
    return round(score, 1)

# ================================
# PORTFOLIO OPTIMIZATION (RISK PARITY)
# ================================
def calculate_risk_parity(selected_stocks_data):
    returns_df = pd.DataFrame({
        code: data['Close'].pct_change()
        for code, data in selected_stocks_data.items()
    }).dropna()

    vols = returns_df.std()
    if vols.sum() == 0: return {code: 1.0/len(selected_stocks_data) for code in selected_stocks_data}
    
    inv_vol = 1 / vols
    weights = inv_vol / inv_vol.sum()
    return weights.to_dict()

# ================================
# AI COMMENTARY
# ================================
def ai_portfolio_commentary(code, score, weight, tech, fund, current_inflation, api_key):
    try:
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        selected_model = next((m for m in available_models if "1.5-flash" in m), "models/gemini-1.5-flash")
        model = genai.GenerativeModel(selected_model)

        prompt = f"""
        Kurumsal Hedge Fon Yöneticisisin. {code} hissesi seçildi.
        MAKRO VERİ: TCMB Güncel Enflasyon: %{current_inflation*100:.2f}
        VERİ KAYNAĞI: {fund['source']}
        - Skor: {score}/100 | Portföy Ağırlığı: %{weight*100:.1f}
        - Rejim: {tech['regime']} (Volatilite: {tech['volatility']})
        - Temel: Dinamik Reel Büyüme %{fund['real_growth']}, PEG: {fund['peg']}
        
        GÖREV:
        1. TCMB Enflasyon oranını dikkate alarak şirketin reel büyüme performansını (Fisher denklemi sonucu) yorumla.
        2. Peter Lynch mantığına göre analiz et.
        3. Risk Paritesi algoritmasının neden bu ağırlığı verdiğini açıkla.
        
        JSON DÖNDÜR (Türkçe):
        {{
          "advice": "BUY / ACCUMULATE",
          "summary": "Makro (TCMB) destekli reel büyüme ve ağırlık açıklaması",
          "reason": "Lynch analiz onayı",
          "risk": "Rejim ve makro riskler"
        }}
        """
        res = model.generate_content(prompt)
        return json.loads(repair_json(res.text.replace('```json', '').replace('```', '').strip()))
    except:
        return {"advice": "ERROR", "summary": "-", "reason": "-", "risk": "-"}

# ================================
# MAIN ENGINE
# ================================
def main():
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "THYAO.IS,AKSA.IS,TUPRS.IS,ASELS.IS,SISE.IS,BIMAS.IS")
    capital_input = float(os.getenv("PORTFOLIO_CAPITAL", START_CAPITAL))
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    
    print("🚀 Macro-Quant Motoru Başlatılıyor...")
    
    # DİNAMİK ENFLASYONU ÇEK
    current_inflation = get_tcmb_inflation()
    print(f"🇹🇷 TCMB Güncel YoY Enflasyon: %{current_inflation*100:.2f}")

    all_data, scores, fundamentals, technicals = {}, {}, {}, {}

    for code in stock_codes:
        print(f"🔍 {code} taranıyor...")
        ticker = yf.Ticker(code)
        df = ticker.history(period="2y")
        
        if not df.empty and len(df) > 200:
            df, tech = get_technical_and_regime(df)
            fund = get_fundamental(ticker, code, current_inflation) # Enflasyonu fonksiyona paslıyoruz
            score = factor_score(tech, fund)
            
            all_data[code] = df
            scores[code] = score
            fundamentals[code] = fund
            technicals[code] = tech
            time.sleep(2) 
            
    selected_codes = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]
    selected_data = {code: all_data[code] for code in selected_codes}
    weights = calculate_risk_parity(selected_data)
    
    final_portfolio = []
    
    for code in selected_codes:
        weight = weights[code]
        allocated_capital = capital_input * weight
        price = technicals[code]['price']
        lot_size = math.floor(allocated_capital / price) if price > 0 else 0
        
        ai = ai_portfolio_commentary(code, scores[code], weight, technicals[code], fundamentals[code], current_inflation, api_key)
        time.sleep(8) 
        
        final_portfolio.append({
            "code": code, "price": price, "score": scores[code],
            "weight": weight, "lot": lot_size, "allocated": allocated_capital,
            "regime": technicals[code]['regime'], "source": fundamentals[code]['source'], "ai": ai
        })

    md = "<small>\n\n## 📊 Dr. Ömer - Macro-Quant Portfolio Terminal (v9.0)\n\n"
    md += f"**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')} | **Toplam Sermaye:** {capital_input:,.0f} TL\n"
    md += f"🇹🇷 **TCMB EVDS Enflasyon (YoY):** %{current_inflation*100:.2f} (Fisher Reel Büyüme Çarpanı)\n\n"
    md += "| Hisse | Fiyat | Rejim | Puan | Veri Kaynağı | Ağırlık | Alınacak Lot |\n"
    md += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    
    for r in final_portfolio:
        regime_icon = "🟢" if r['regime'] == "TREND_LOW_VOL" else ("🟡" if "HIGH_VOL" in r['regime'] else "🔴")
        src_icon = "🔥 İş Yatırım" if "ISYATIRIM" in r['source'] else "⚠️ YF"
        md += f"| **{r['code']}** | {r['price']} | {regime_icon} {r['regime']} | {r['score']} | {src_icon} | **%{r['weight']*100:.1f}** | **{r['lot']}** |\n"
    
    md += "\n---\n### 🔍 Kurumsal Portföy Komitesi (Makro-Ekonomik Yorumlar)\n"
    for r in final_portfolio:
        ai = r['ai']
        md += f"#### 🔹 {r['code']} (Ağırlık: %{r['weight']*100:.1f})\n"
        md += f"- **Makro-Reel Büyüme Analizi:** {ai.get('summary', '-')}\n"
        md += f"- **Lynch Onayı:** {ai.get('reason', '-')}\n"
        md += f"- **Risk Radarı:** {ai.get('risk', '-')}\n\n---\n"
    md += "</small>"
    
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f: f.write(md)

if __name__ == "__main__":
    main()
