# -*- coding: utf-8 -*-
import io
import logging
import os
import requests
import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("StrategyEngine")

SHEET_URL = os.getenv("SHEET_URL", "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv")
PERIOD = "2y"
MIN_DAYS = {"vol": 21, "rsi": 14, "momentum": 22, "ema200": 200, "atr": 14}
KNOWN_INVALID_TICKERS = set(os.getenv("KNOWN_INVALID_TICKERS", "").upper().split(",")) - {""}
VOL_LOW_THRESHOLD = float(os.getenv("VOL_LOW_THRESHOLD", "30.0"))

TARGET_WEIGHTS = {"VOO": 15.0, "SCHD": 10.0, "QQQM": 10.0, "VXUS": 15.0, "O": 15.0, "SMH": 7.5, "AIS": 7.5, "NASA": 7.5}

def get_portfolio():
    try:
        response = requests.get(SHEET_URL, timeout=15)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.content.decode("utf-8-sig")))
        df.columns = df.columns.str.strip().str.lower()
        df = df.dropna(subset=["hisse"])
        df["hisse"] = df["hisse"].astype(str).str.strip().str.upper().str.split(":").str[-1]
        df["lot"] = df["lot"].astype(str).str.replace(",", ".", regex=False).pipe(pd.to_numeric, errors="coerce").fillna(0)
        return dict(zip(df["hisse"], df[df["lot"] > 0]["lot"]))
    except Exception as e:
        log.error(f"Portföy yüklenemedi: {e}"); return {}

def analyze_ticker(ticker, df):
    close, n = df["Close"].dropna(), len(df["Close"].dropna())
    if n < 2: return {"ticker": ticker, "error": "veri_yok"}
    result = {"ticker": ticker, "last_price": round(float(close.iloc[-1]), 2), "days_available": n}
    if n >= MIN_DAYS["vol"]:
        result["annual_vol_pct"] = round(np.log(close / close.shift(1)).dropna().std() * np.sqrt(252 if n >= 252 else n) * 100, 2)
    if n >= MIN_DAYS["rsi"]:
        delta = close.diff()
        gain, loss = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(), (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        result["rsi"] = round(float((100 - (100 / (1 + gain / loss.replace(0, np.nan)))).iloc[-1]), 2)
    if n >= MIN_DAYS["ema200"]:
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        result["ema200"], result["trend"] = round(float(ema200), 2), ("📈 YUKARI" if close.iloc[-1] > ema200 else "📉 AŞAĞI")
    return result

def compute_action(r):
    trend_up, rsi, vol = "YUKARI" in r.get("trend", ""), r.get("rsi"), r.get("annual_vol_pct")
    if rsi is None: return "⏳ Yetersiz Veri"
    if rsi > 70 and trend_up: return "🔴 KAR AL"
    if trend_up and rsi < 60 and (vol is None or vol < VOL_LOW_THRESHOLD): return "🟢 EKLE"
    return "⚪ NÖTR" if rsi >= 60 else "🟡 TUT"

def main():
    portfolio = get_portfolio()
    tickers = [t for t in portfolio.keys() if t not in KNOWN_INVALID_TICKERS]
    if not tickers: return
    raw = yf.download(tickers, period=PERIOD, auto_adjust=True, progress=False)
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex): raw = pd.concat({tickers[0]: raw}, axis=1).swaplevel(axis=1)
    
    results = [analyze_ticker(t, raw.xs(t, axis=1, level=1 if isinstance(raw.columns, pd.MultiIndex) else 0) if isinstance(raw.columns, pd.MultiIndex) else raw) for t in tickers]
    
    md = "# 📊 Strateji Motoru Raporu\n\n| Hisse | Fiyat | EMA-200 | Vol% | RSI | Aksiyon |\n| :--- | ---: | ---: | ---: | ---: | ---: |\n"
    for r in results:
        if "error" in r: md += f"| **{r['ticker']}** | — | — | — | — | ⚠️ {r['error']} |\n"; continue
        action = compute_action(r)
        display_ticker = f"🟢 **{r['ticker']}**" if action == "🟢 EKLE" else f"**{r['ticker']}**"
        vol = r.get("annual_vol_pct")
        vol_str = f"**`%{vol:.2f}`**" if vol and vol > VOL_LOW_THRESHOLD else (f"%{vol:.2f}" if vol else "—")
        md += f"| {display_ticker} | ${r.get('last_price', 0):.2f} | {'$'+str(r.get('ema200')) if r.get('ema200') else '—'} | {vol_str} | {r.get('rsi', '—')} | **{action}** |\n"
    
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.getenv("GITHUB_STEP_SUMMARY"), "w", encoding="utf-8") as f: f.write(md)
    print(md)

if __name__ == "__main__": main()
