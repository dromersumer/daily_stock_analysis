# -*- coding: utf-8 -*-
"""
Apex Terminal — Quant Engine v25.8
"""

import os
import json
import math
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("ApexTerminal")

# ── Ortam Değişkenleri ───────────────────────────────────────────────────────
PORTFOLIO_TYPE   = os.getenv("PORTFOLIO_TYPE", "ABD").upper()
START_CAPITAL    = float(os.getenv("PORTFOLIO_CAPITAL", "10000" if PORTFOLIO_TYPE == "ABD" else "100000"))
MAX_PORTFOLIO_SIZE   = int(os.getenv("MAX_PORTFOLIO_SIZE", "19"))
MAX_WEIGHT_PER_STOCK = float(os.getenv("MAX_WEIGHT", "0.35"))
CORR_THRESHOLD   = float(os.getenv("CORR_THRESHOLD", "0.85"))

# ── Analiz Fonksiyonları ──────────────────────────────────────────────────────

def get_technical(df: pd.DataFrame) -> Optional[dict]:
    if df is None or len(df) < 201: return None
    close = df["Close"].astype(float)
    high  = df["High"].astype(float)
    low   = df["Low"].astype(float)
    ema200 = close.ewm(span=200, adjust=False).mean()
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()
    vol = close.pct_change().rolling(20).std() * math.sqrt(252)
    last = df.iloc[-1]
    return {
        "price": round(float(close.iloc[-1]), 4),
        "atr": round(float(atr.iloc[-1]), 4),
        "vol": float(vol.iloc[-1]),
        "regime": "TREND" if float(close.iloc[-1]) > float(ema200.iloc[-1]) else "WEAK"
    }

def check_correlation_risks(candidates, corr_matrix, threshold):
    alerts = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            s1, s2 = candidates[i], candidates[j]
            if s1 in corr_matrix.index and s2 in corr_matrix.index:
                rho = corr_matrix.loc[s1, s2]
                if abs(rho) >= threshold:
                    alerts.append({"pair": f"{s1} - {s2}", "rho": round(float(rho), 3), "msg": "Yüksek korelasyon."})
    return alerts

# ── Ana Motor ──────────────────────────────────────────────────────────────

def main():
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stocks = [s.strip().upper() for s in os.getenv("STOCK_LIST", "VOO,SCHD,QQQM,SPUS,VXUS,O,WPC,SMH,NVDA,AVGO,GOOG,CAT,ASPI").split(",") if s.strip()]
    
    raw = yf.download(tickers=stocks, period="2y", group_by="ticker", progress=False)
    
    techs = {}
    for s in stocks:
        if s in raw.columns.get_level_values(0):
            df = raw[s].dropna(how="all")
            tech = get_technical(df)
            if tech is not None: techs[s] = tech
    
    if not techs: return

    # Skorlama ve Ağırlık
    scores = {s: (40 if t["regime"] == "TREND" else 0) + (max(1 - t["vol"], 0) * 30) for s, t in techs.items()}
    selected = sorted(scores, key=scores.get, reverse=True)[:MAX_PORTFOLIO_SIZE]
    
    inv_vol = {s: 1.0 / max(techs[s]["vol"], 0.05) for s in selected}
    weights = {s: inv_vol[s] / sum(inv_vol.values()) for s in selected}

    # Korelasyon
    log_rets = pd.DataFrame({s: np.log(raw[s]["Close"] / raw[s]["Close"].shift(1)) for s in selected}).dropna(how="all")
    risk_alerts = check_correlation_risks(selected, log_rets.corr(), CORR_THRESHOLD)

    target = []
    for s in selected:
        t = techs[s]
        w = weights[s]
        price = t["price"]
        stop = round(price - (t["atr"] * (2.0 + (t["vol"] * 2.0))), 2)
        target.append({"code": s, "weight": w, "lot": math.floor((START_CAPITAL * w) / price), "price": price, "stop": stop, "vol": t["vol"]})

    # Rapor Oluşturma
    md = f"# 🏦 Apex Terminal v25.8\n\n### 🎯 HEDEF PORTFÖY\n| Hisse | Ağırlık | Lot | Fiyat | V | Stop |\n| :--- | ---: | ---: | ---: | ---: | ---: |\n"
    for t in target: 
        md += f"| **{t['code']}** | %{t['weight']*100:.1f} | {t['lot']} | {t['price']} | {t['vol']:.2f} | {t['stop']} |\n"
    
    if risk_alerts:
        md += "\n### ⚠️ Korelasyon Risk Uyarıları\n| Hisse Çifti | ρ (Rho) | Durum |\n| :--- | ---: | :--- |\n"
        for a in risk_alerts: md += f"| **{a['pair']}** | {a['rho']:.2f} | {a['msg']} |\n"

    md += "\n### 📝 Terimler Sözlüğü\n| Terim | Açıklama |\n| :--- | :--- |\n| **Ağırlık** | Portföydeki sermaye dağılım oranı (%) |\n| **V** | Yıllık oynaklık (yüksek V = yüksek risk). |\n| **Dinamik Stop** | Fiyat - (ATR * (2.0 + V*2.0)). |\n"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f: f.write(md)
    else: print(md)

if __name__ == "__main__":
    main()
