# -*- coding: utf-8 -*-
# main.py — Apex Terminal v27.7
import io, logging, os, requests, numpy as np, pandas as pd, yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ApexTerminal")

# ── Eşik ve Ayarlar ───────────────────────────────────────────────────────────
SHEET_URL         = os.getenv("SHEET_URL") or "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"
PERIOD            = "2y"
ATR_WINDOW        = 14
VOL_LOW_THRESHOLD = float(os.getenv("VOL_LOW_THRESHOLD") or "30.0")

# Güncellenmiş Hedef Ağırlıklar
TARGET_WEIGHTS    = {
    "VOO": 15.0, "SCHD": 10.0, "QQQM": 5.0, "VXUS": 15.0, 
    "O": 7.5, "SMH": 7.5, "AIS": 7.5, "NASA": 7.5, "SPUS": 5.0, "WPC": 7.5
}

# ── Portföy Yükleme ────────────────────────────────────────────────────────────
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

# ── Teknik Analiz ve Aksiyon Motoru ────────────────────────────────────────────
def analyze_ticker(ticker: str, df: pd.DataFrame) -> dict:
    close = df["Close"].dropna()
    n     = len(close)
    if n < 2: return {"ticker": ticker, "error": "veri_yok"}
    res = {"ticker": ticker, "last_price": round(float(close.iloc[-1]), 2), "days_available": n}
    if n >= 21: res["annual_vol_pct"] = round(np.log(close / close.shift(1)).dropna().std() * np.sqrt(252 if n >= 252 else n) * 100, 2)
    if n >= 14:
        delta = close.diff(); gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(); loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        res["rsi"] = round(float((100 - (100 / (1 + gain / loss.replace(0, np.nan)))).iloc[-1]), 2)
    if n >= 200:
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        res["ema200"] = round(float(ema200), 2); res["trend"] = "📈 YUKARI" if close.iloc[-1] > ema200 else "📉 AŞAĞI"
        res["trend_pct"] = round((float(close.iloc[-1]) - float(ema200)) / float(ema200) * 100, 2)
    return res

def compute_action(r: dict) -> str:
    trend_up = "YUKARI" in r.get("trend", ""); rsi = r.get("rsi"); vol = r.get("annual_vol_pct"); has_ema = r.get("ema200") is not None
    if rsi is None: return "⏳ Yetersiz Veri"
    if rsi > 70 and trend_up: return "🔴 KAR AL"
    if rsi > 70 and "AŞAĞI" in r.get("trend", ""): return "🔴 SAT / ÇIKIŞ"
    if has_ema and "AŞAĞI" in r.get("trend", "") and rsi < 40: return "⚠️ İZLE"
    if trend_up and rsi < 60 and ((vol is None) or (vol < VOL_LOW_THRESHOLD)): return "🟢 EKLE"
    return "🟡 TUT" if (trend_up and 60 <= rsi <= 70) else "⚪ NÖTR"

# ── Rapor Oluşturma ve Main ──────────────────────────────────────────────────
def build_report(portfolio: dict, results: list) -> str:
    price_map = {r["ticker"]: r.get("last_price", 0.0) for r in results if "error" not in r}
    total_val = sum(lots * price_map.get(t, 0) for t, lots in portfolio.items()) or 1.0
    md = "# 🚀 Apex Terminal Raporu\n\n## 💼 Portföy Dağılımı\n| Hisse | Lot | Fiyat | Değer ($) | Mevcut % | Hedef % |\n| :--- | ---: | ---: | ---: | ---: | ---: |\n"
    for t, lots in portfolio.items():
        price = price_map.get(t, 0); val = lots * price; tgt = TARGET_WEIGHTS.get(t)
        md += f"| **{t}** | {lots} | {'$'+str(price) if price else '—'} | ${val:,.2f} | %{val/total_val*100:.1f} | {'%'+str(tgt) if tgt else '—'} |\n"
    md += f"\n> 💰 **Toplam:** ${total_val:,.2f}\n\n## 📈 Teknik Analiz\n| Hisse | Fiyat | EMA-200 | Trend | RSI | Aksiyon |\n| :--- | ---: | ---: | :--- | ---: | ---: |\n"
    for r in results:
        t = r.get("ticker", "?")
        if "error" in r: md += f"| **{t}** | — | — | — | — | ⚠️ {r['error']} |\n"; continue
        md += f"| **{t}** | ${r['last_price']:.2f} | {'$'+str(r['ema200']) if r.get('ema200') else '—'} | {r.get('trend', '—')} | {r.get('rsi', '—')} | **{compute_action(r)}** |\n"
    return md

def main():
    portfolio = get_portfolio()
    if not portfolio: return
    tickers = list(portfolio.keys())
    raw = yf.download(tickers, period=PERIOD, auto_adjust=True, progress=False)
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex): raw = pd.concat({tickers[0]: raw}, axis=1).swaplevel(axis=1)
    results = [analyze_ticker(t, raw.xs(t, axis=1, level=(1 if isinstance(raw.columns, pd.MultiIndex) else -1)) if t in raw.columns.get_level_values(1) else raw) for t in tickers]
    md = build_report(portfolio, results)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.getenv("GITHUB_STEP_SUMMARY"), "w", encoding="utf-8") as f: f.write(md)
    print(md)

if __name__ == "__main__": main()
