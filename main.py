# -*- coding: utf-8 -*-
import os, sys, json, math, time, smtplib
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from json_repair import repair_json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ================================
# CONFIG
# ================================
START_CAPITAL = 100000     # Varsayılan Portföy Sermayesi (TL)
INFLATION_EST = 0.50       # BIST TMS 29 İçin Tahmini Enflasyon
MAX_PORTFOLIO_SIZE = 5     # Portföye alınacak max hisse sayısı
LOOKBACK_DAYS = 252        # 1 Yıllık işlem günü

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
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # Volatility & Momentum (Sizin eklediğiniz Factor Modeli)
    returns = close.pct_change()
    df['volatility'] = returns.rolling(20).std() * np.sqrt(LOOKBACK_DAYS)
    df['momentum'] = close.pct_change(60) # 3 Aylık Momentum

    last = df.iloc[-1]

    # REGIME DETECTION
    regime = "RANGE_OR_DOWN"
    if last['Close'] > last['ema200'] and last['volatility'] < 0.35:
        regime = "TREND_LOW_VOL" # Altın Rejim (Trend var, risk düşük)
    elif last['Close'] > last['ema200']:
        regime = "TREND_HIGH_VOL" # Riskli Trend (Testere ihtimali)

    return df, {
        "price": round(last['Close'], 2),
        "ema21": round(last['ema21'], 2),
        "ema200": round(last['ema200'], 2),
        "rsi": round(last['rsi'], 2),
        "volatility": round(last['volatility'], 2),
        "momentum": round(last['momentum'], 2),
        "regime": regime
    }

# ================================
# FUNDAMENTAL ENGINE (TMS 29)
# ================================
def get_fundamental(ticker):
    try:
        info = ticker.info
        rev_growth = (info.get("revenueGrowth", 0) or 0) * 100
        margin = (info.get("profitMargins", 0) or 0) * 100
        peg = info.get("trailingPegRatio", None)

        # Fisher Denklemi ile Reel Büyüme
        real_growth = ((1 + rev_growth/100) / (1 + INFLATION_EST)) - 1

        return {
            "real_growth": round(real_growth * 100, 2),
            "margin": round(margin, 2),
            "peg": round(peg, 2) if peg is not None else None
        }
    except:
        return {"real_growth": 0, "margin": 0, "peg": None}

# ================================
# MULTI-FACTOR SCORING ENGINE
# ================================
def factor_score(tech, fund):
    score = 0
    
    # 1. Momentum & Trend Faktörü (Sizin Kodunuz)
    if tech['momentum'] > 0: score += 15
    if tech['momentum'] > 0.1: score += 10 # Güçlü momentum bonusu
    if tech['price'] > tech['ema200']: score += 15
    
    # 2. Volatilite Faktörü (Düşük volatilite = Güvenli Liman)
    if tech['volatility'] < 0.35: score += 10
    if tech['regime'] == "TREND_LOW_VOL": score += 10

    # 3. Temel Analiz & TMS 29 Faktörü (Lynch Mantığı)
    if fund['real_growth'] > 10: score += 20
