# -*- coding: utf-8 -*-
# main.py — Apex Terminal v31.0 (Final Production Ready)
import io, logging, os, requests, numpy as np, pandas as pd, yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ApexTerminal")

# ── Ayarlar ───────────────────────────────────────────────────────────────────
SHEET_URL = os.getenv("SHEET_URL") or "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"
PERIOD, ATR_WINDOW, ATR_MULTIPLIER = "2y", 14, 2.5
TARGET_WEIGHTS = {
    "VOO": 15.0, "SCHD": 10.0, "QQQM": 5.0, "SPUS": 5.0, 
    "VXUS": 15.0, "O": 7.5, "WPC": 7.5, "SMH": 7.5, 
    "AIS": 7.5, "NASA": 7.5
}

def get_portfolio() -> dict:
    try:
        r = requests.get(SHEET_URL, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")))
        df.columns = df.columns.str.strip().str.lower()
        df = df.dropna(subset=["hisse"])
        df["hisse"] = df["hisse"].astype(str).str.strip().str.upper().str.split(":").str[-1]
        df["lot"]   = df["lot"].astype(str).str.replace(",", ".", regex=False).pipe(pd.to_numeric, errors="coerce").fillna(0)
        return dict(zip(df["hisse"], df[df["lot"] > 0]["lot"]))
    except Exception as e:
        log.error(f"Portföy yüklenemedi: {e}")
        return {}

def analyze_ticker(ticker: str, df: pd.DataFrame) -> dict:
    close = df["Close"].dropna()
    high, low = df["High"].dropna(), df["Low"].dropna()
    n = len(close)
    
    # NASA gibi yeni varlıklar için hata korumalı eşik (EMA200 yoksa en az 30 gün veri şart)
    if n < 30: return {"ticker": ticker, "error": "veri_yetersiz"}
    
    last_p = float(close.iloc[-1])
    ema50  = close.ewm(span=50, adjust=False).mean().iloc[-1]
    ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1] if n >= 200 else None
    
    tr = pd.concat([high-low, (high-close.shift(1)).abs(), (low-close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/ATR_WINDOW, adjust=False).mean().iloc[-1]
    
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi   = round(float((100 - (100 / (1 + gain / loss.replace(0, np.nan)))).iloc[-1]), 2)
    
    return {
        "ticker": ticker, "last_price": round(last_p, 2), "rsi": rsi,
        "ema50": round(ema50, 2), "ema200": round(ema200, 2) if ema200 else None,
        "stop_loss": round(last_p - (ATR_MULTIPLIER * atr), 2),
        "trend_state": "BULL" if ema200 and last_p > ema50 > ema200 else ("BEAR" if ema200 and last_p < ema50 < ema200 else "NEUTRAL")
    }

def compute_action(r: dict) -> str:
    p, e50, e200, rsi = r.get("last_price", 0), r.get("ema50", 0), r.get("ema200", 0), r.get("rsi", 0)
    if p > (e50 * 1.15) and rsi > 75: return "🔴 KAR AL"
    if e200 and p > e50 > e200 and 40 < rsi < 60: return "🟢 AL"
    if p > e50 and 60 <= rsi <= 70: return "🟡 TUT"
    if e200 and p < e50 < e200 and 40 <= rsi <= 50: return "🔴 SAT"
    return "⚪ NÖTR"

def build_report(portfolio: dict, results: list) -> str:
    price_map = {r["ticker"]: r.get("last_price", 0.0) for r in results if "error" not in r}
    total_val = sum(lots * price_map.get(t, 0) for t, lots in portfolio.items()) or 1.0
    
    md = "# 🚀 Apex Terminal Raporu (Savaş Modu v2.5)\n\n## 💼 Portföy Dağılımı\n| Hisse | Değer ($) | Mevcut % | Hedef % |\n| :--- | ---: | ---: | ---: |\n"
    for t, lots in portfolio.items():
        val = lots * price_map.get(t, 0)
        md += f"| **{t}** | ${val:,.2f} | %{(val/total_val*100):.1f} | {'%'+str(TARGET_WEIGHTS.get(t)) if TARGET_WEIGHTS.get(t) else '—'} |\n"
    
    md += f"\n> 💰 **Toplam:** ${total_val:,.2f} | 🛡️ **ATR Çarpanı:** {ATR_MULTIPLIER}x\n\n## 📈 Teknik Analiz & Stop Loss\n| Hisse | Fiyat | Stop Loss | Trend | RSI | Aksiyon |\n| :--- | ---: | ---: | :--- | ---: | ---: |\n"
    for r in results:
        t = r.get("ticker", "?")
        if "error" in r: md += f"| **{t}** | — | — | — | — | ⚠️ {r['error']} |\n"; continue
        stop_alert = "🚨" if r['last_price'] < (r['stop_loss'] * 1.03) else ""
        md += f"| **{t}** | ${r['last_price']:.2f} | ${r['stop_loss']} {stop_alert} | {r.get('trend_state', 'N/A')} | {r.get('rsi', '—')} | **{compute_action(r)}** |\n"
    return md

def main():
    portfolio = get_portfolio()
    if not portfolio: return
    tickers = list(portfolio.keys())
    raw = yf.download(tickers, period=PERIOD, auto_adjust=True, progress=False)
    
    level = 1 if isinstance(raw.columns, pd.MultiIndex) and tickers[0] in raw.columns.get_level_values(1) else (0 if isinstance(raw.columns, pd.MultiIndex) else -1)
    results = [analyze_ticker(t, raw.xs(t, axis=1, level=level) if level >= 0 else raw) for t in tickers]
    
    md = build_report(portfolio, results)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.getenv("GITHUB_STEP_SUMMARY"), "w", encoding="utf-8") as f: f.write(md)
    print(md)

if __name__ == "__main__": main()
