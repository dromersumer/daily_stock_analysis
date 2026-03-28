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
# SAFE HELPERS
# ================================
def safe_float(x, default=0.0):
    try: return float(x)
    except: return default

def safe_round(x, n=2):
    try: return round(float(x), n) if pd
