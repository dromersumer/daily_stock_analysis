# -*- coding: utf-8 -*-
# main.py — Apex Terminal v27.6 (Crash-Proof Edition)
import io, logging, os, requests, numpy as np, pandas as pd, yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ApexTerminal")

# ── Eşik ve Ayarlar (Boş string korumalı) ──────────────────────────────────────
SHEET_URL         = os.getenv("SHEET_URL") or "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"
PERIOD            = "2y"
ATR_WINDOW        = 14
VOL_LOW_THRESHOLD = float(os.getenv("VOL_LOW_THRESHOLD") or "30.0")
TARGET_WEIGHTS    = {"VOO": 15.0, "SCHD": 10.0, "QQQM": 10.0, "VXUS": 15.0, "O": 15.0, "SMH": 7.5, "AIS": 7.5, "NASA": 7.5}


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


# ── Teknik Analiz ──────────────────────────────────────────────────────────────
def analyze_ticker(ticker: str, df: pd.DataFrame) -> dict:
    close = df["Close"].dropna()
    n     = len(close)
    if n < 2:
        return {"ticker": ticker, "error": "veri_yok"}

    res = {"ticker": ticker, "last_price": round(float(close.iloc[-1]), 2), "days_available": n}

    # Yıllık Volatilite (min 21 gün)
    if n >= 21:
        res["annual_vol_pct"] = round(
            np.log(close / close.shift(1)).dropna().std() * np.sqrt(252 if n >= 252 else n) * 100, 2
        )

    # RSI — Wilder (min 14 gün)
    if n >= 14:
        delta = close.diff()
        gain  = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        res["rsi"] = round(float((100 - (100 / (1 + gain / loss.replace(0, np.nan)))).iloc[-1]), 2)

    # EMA-200 / Trend (min 200 gün)
    if n >= 200:
        ema200           = close.ewm(span=200, adjust=False).mean().iloc[-1]
        res["ema200"]    = round(float(ema200), 2)
        res["trend"]     = "📈 YUKARI" if close.iloc[-1] > ema200 else "📉 AŞAĞI"
        res["trend_pct"] = round((float(close.iloc[-1]) - float(ema200)) / float(ema200) * 100, 2)

    # ATR — Wilder (min 14 gün)
    if n >= 14 and "High" in df.columns and "Low" in df.columns:
        high, low  = df["High"].dropna(), df["Low"].dropna()
        prev_close = close.shift(1)
        tr         = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        atr_val    = tr.ewm(alpha=1/ATR_WINDOW, adjust=False).mean().iloc[-1]
        res["atr_pct"] = round(float(atr_val) / float(close.iloc[-1]) * 100, 2)

    # Momentum 1M (min 22 gün)
    if n >= 22:
        res["momentum_1m_pct"] = round((float(close.iloc[-1]) / float(close.iloc[-22]) - 1) * 100, 2)

    return res


def compute_action(r: dict) -> str:
    """6 kurallı aksiyon motoru."""
    trend_up   = "YUKARI" in r.get("trend", "")
    trend_down = "AŞAĞI"  in r.get("trend", "")
    rsi        = r.get("rsi")
    vol        = r.get("annual_vol_pct")
    has_ema    = r.get("ema200") is not None

    if rsi is None:
        return "⏳ Yetersiz Veri"
    if rsi > 70 and trend_up:
        return "🔴 KAR AL"
    if rsi > 70 and trend_down:
        return "🔴 SAT / ÇIKIŞ"
    if has_ema and trend_down and rsi < 40:
        return "⚠️ İZLE"
    vol_ok = (vol is None) or (vol < VOL_LOW_THRESHOLD)
    if trend_up and rsi < 60 and vol_ok:
        return "🟢 EKLE"
    if trend_up and 60 <= rsi <= 70:
        return "🟡 TUT"
    return "⚪ NÖTR"


# ── Rapor Oluşturma ────────────────────────────────────────────────────────────
def build_report(portfolio: dict, results: list) -> str:
    price_map = {r["ticker"]: r.get("last_price", 0.0) for r in results if "error" not in r}
    total_val = sum(lots * price_map.get(t, 0) for t, lots in portfolio.items()) or 1.0

    # Portföy Dağılımı
    md  = "# 🚀 Apex Terminal Raporu\n\n"
    md += "## 💼 Portföy Dağılımı\n"
    md += "| Hisse | Lot | Fiyat | Değer ($) | Mevcut % | Hedef % |\n"
    md += "| :--- | ---: | ---: | ---: | ---: | ---: |\n"
    for t, lots in portfolio.items():
        price = price_map.get(t, 0)
        val   = lots * price
        tgt   = TARGET_WEIGHTS.get(t)
        md += (
            f"| **{t}** | {lots} | {'$'+str(price) if price else '—'} "
            f"| ${val:,.2f} | %{val/total_val*100:.1f} "
            f"| {'%'+str(tgt) if tgt else '—'} |\n"
        )
    md += f"\n> 💰 **Toplam Portföy Değeri:** ${total_val:,.2f}\n\n"

    # Teknik Analiz
    md += "## 📈 Teknik Analiz\n"
    md += "| Hisse | Fiyat | EMA-200 | Trend | Vol% | ATR% | RSI | Mom 1M% | Aksiyon |\n"
    md += "| :--- | ---: | ---: | :--- | ---: | ---: | ---: | ---: | :---: |\n"
    for r in results:
        t = r.get("ticker", "?")
        if "error" in r:
            md += f"| **{t}** | — | — | — | — | — | — | — | ⚠️ {r['error']} |\n"
            continue
        action    = compute_action(r)
        vol       = r.get("annual_vol_pct")
        vol_str   = f"**`%{vol:.2f}`**" if vol and vol > VOL_LOW_THRESHOLD else (f"%{vol:.2f}" if vol else "—")
        trend_str = r.get("trend", "—")
        if r.get("trend_pct") is not None:
            trend_str += f" ({r['trend_pct']:+.1f}%)"
        ema_str   = f"${r['ema200']}" if r.get("ema200") else "—"
        atr_str   = f"%{r['atr_pct']:.2f}" if r.get("atr_pct") else "—"
        mom_str   = f"{r['momentum_1m_pct']:+.1f}%" if r.get("momentum_1m_pct") is not None else "—"
        md += (
            f"| **{t}** | ${r['last_price']:.2f} | {ema_str} | {trend_str} "
            f"| {vol_str} | {atr_str} | {r.get('rsi', '—')} | {mom_str} | **{action}** |\n"
        )

    # Aksiyon Özeti
    valid  = [r for r in results if "error" not in r]
    groups = {"🟢 EKLE": [], "🔴 KAR AL": [], "🔴 SAT / ÇIKIŞ": [], "⚠️ İZLE": [], "🟡 TUT": []}
    for r in valid:
        a = compute_action(r)
        if a in groups:
            groups[a].append(r["ticker"])
    md += "\n### 📋 Aksiyon Özeti\n"
    for label, tlist in groups.items():
        if tlist:
            md += f"- **{label}:** {', '.join(f'`{t}`' for t in tlist)}\n"

    md += f"\n> ℹ️ *Volatilite eşiği: yıllık **%{VOL_LOW_THRESHOLD:.0f}** altı \"düşük\" kabul edilir.*\n"
    return md


# ── Ana Akış ───────────────────────────────────────────────────────────────────
def _resolve_level(raw: pd.DataFrame, tickers: list) -> int:
    if not isinstance(raw.columns, pd.MultiIndex):
        return -1
    sample = tickers[0]
    if sample in raw.columns.get_level_values(1): return 1
    if sample in raw.columns.get_level_values(0): return 0
    log.warning("MultiIndex level tespit edilemedi, level=1 deneniyor.")
    return 1


def main():
    portfolio = get_portfolio()
    if not portfolio:
        log.error("Portföy boş — SHEET_URL veya Sheet erişim ayarlarını kontrol edin.")
        return

    tickers = list(portfolio.keys())
    log.info(f"Analiz edilecek: {tickers}")

    raw = yf.download(tickers, period=PERIOD, auto_adjust=True, progress=False)

    # Tek ticker edge case
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw = pd.concat({tickers[0]: raw}, axis=1).swaplevel(axis=1)

    level   = _resolve_level(raw, tickers)
    results = []

    for t in tickers:
        try:
            ticker_df = raw.xs(t, axis=1, level=level) if level >= 0 else raw
            if ticker_df["Close"].dropna().empty:
                log.warning(f"{t}: Veri yok (delist veya geçersiz sembol).")
                results.append({"ticker": t, "error": "veri_yok"})
                continue
            results.append(analyze_ticker(t, ticker_df))
        except Exception as e:
            log.error(f"{t} analiz hatası: {e}")
            results.append({"ticker": t, "error": str(e)})

    md = build_report(portfolio, results)

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)
    log.info("Apex Terminal analizi tamamlandı.")


if __name__ == "__main__":
    main()
