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
        equity = next((float(i['value1']) for i in raw_data if i.get('itemDescTR') == 'ÖZKAYNAKLAR'), 1) # Div
