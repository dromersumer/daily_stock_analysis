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
# TECHNICAL & REGIME ENGINE
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

    returns = close.pct_change()
    df['volatility'] = returns.rolling(20).std() * np.sqrt(LOOKBACK_DAYS)
    df['momentum'] = close.pct_change(60)

    last = df.iloc[-1]
    
    # REGIME DETECTION
    if last['Close'] > last['ema200'] and last['volatility'] < 0.35:
        regime = "TREND_LOW_VOL" # Boğa (İstikrarlı)
    elif last['Close'] > last['ema200']:
        regime = "TREND_HIGH_VOL" # Boğa (Oynak)
    else:
        regime = "RANGE_OR_DOWN" # Ayı veya Testere

    return df, {
        "price": round(last['Close'], 2),
        "ema200": round(last['ema200'], 2),
        "rsi": round(last['rsi'], 2),
        "volatility": round(last['volatility'], 2),
        "momentum": round(last['momentum'], 2),
        "regime": regime
    }

# ================================
# DATA LAYER: PARSING ENGINE
# ================================
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

def parse_fundamentals(raw_data):
    """THE BIGGEST LEAK CLOSED: İş Yatırım JSON Parsing"""
    try:
        # Hasılat (Revenue) Tespiti
        rev_curr = next((float(item['value1']) for item in raw_data if 'Hasılat' in str(item.get('itemDescTR',''))), 0)
        rev_prev = next((float(item['value2']) for item in raw_data if 'Hasılat' in str(item.get('itemDescTR',''))), 0)
        
        # Net Kar Tespiti
        net_inc = next((float(item['value1']) for item in raw_data if 'Dönem Karı' in str(item.get('itemDescTR',''))), 0)
        
        nominal_growth = (rev_curr / rev_prev - 1) * 100 if rev_prev > 0 else 0
        margin = (net_inc / rev_curr) * 100 if rev_curr > 0 else 0
        
        return nominal_growth, margin
    except: return 0, 0

def get_fundamental(ticker_obj, code, current_inflation):
    clean_code = code.replace(".IS", "")
    is_data = get_isyatirim_data(clean_code)
    
    # 1. PRIMARY: İş Yatırım (Parsed)
    if is_data["status"] == "success":
        source = "ISYATIRIM"
        nom_growth, margin = parse_fundamentals(is_data["raw_data"])
        peg = ticker_obj.info.get("trailingPegRatio", None) # PEG hala YF'den (hesaplaması komplekstir)
    else:
        # 2. FALLBACK: YFinance
        source = "YFINANCE"
        info = ticker_obj.info
        nom_growth = (info.get("revenueGrowth", 0) or 0) * 100
        margin = (info.get("profitMargins", 0) or 0) * 100
        peg = info.get("trailingPegRatio", None)

    # FISHER DENKLEMİ
    real_growth = ((1 + nom_growth/100) / (1 + current_inflation)) - 1

    return {
        "source": source,
        "real_growth": round(real_growth * 100, 2),
        "margin": round(margin, 2),
        "peg": round(peg, 2) if peg is not None else None
    }

# ================================
# REGIME-SWITCHING
