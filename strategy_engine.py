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

# Sheet URL: Önce env'den, yoksa fallback
SHEET_URL = os.getenv("SHEET_URL", "https://docs.google.com/spreadsheets/d/1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv")
PERIOD = "2y"
ATR_WINDOW = 14

MIN_DAYS = {"vol": 21, "rsi": 14, "momentum": 22, "ema200": 200, "atr": 14}
KNOWN_INVALID_TICKERS = set(os.getenv("KNOWN_INVALID_TICKERS", "").upper().split(",")) - {""}
VOL_LOW_THRESHOLD = float(os.getenv("VOL_LOW_THRESHOLD", "30.0"))

TARGET_WEIGHTS: dict[str, float] = {
    "VOO": 15.0, "SCHD": 10.0, "QQQM": 10.0, "VXUS": 15.0,
    "O": 15.0, "SMH": 7.5, "AIS": 7.5, "NASA": 7.5,
}

def get_portfolio() -> dict:
    if not SHEET_URL:
        log.error("Portföy yüklenemedi: SHEET_URL tanımlı değil.")
        return {}
    try:
        response = requests.get(SHEET_URL, timeout=15)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.content.decode("utf-8-sig")))
        df.columns = df.columns.str.strip().str.lower()
        df = df.dropna(subset=["hisse"])
        df["hisse"] = df["hisse"].astype(str).str.strip().str.upper().str.split(":").str[-1]
        df["lot"] = df["lot"].astype(str).str.replace(",", ".", regex=False).pipe(pd.to_numeric, errors="coerce").fillna(0)
        result = dict(zip(df["hisse"], df[df["lot"] > 0]["lot"]))
        log.info(f"Portföy yüklendi: {list(result.keys())}")
        return result
    except requests.exceptions.Timeout:
        log.error("Portföy yüklenemedi: Bağlantı zaman aşımı (15s). SHEET_URL erişilebilir mi?")
        return {}
    except requests.exceptions.HTTPError as e:
        log.error(f"Portföy yüklenemedi: HTTP {e.response.status_code} — Sheet gizli veya URL yanlış olabilir.")
        return {}
    except KeyError as e:
        log.error(f"Portföy yüklenemedi: Sütun bulunamadı → {e}. 'hisse' ve 'lot' sütunları mevcut mu?")
        return {}
    except Exception as e:
        log.error(f"Portföy yüklenemedi: {e}")
        return {}

def compute_atr(high, low, close, window=14):
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/window, adjust=False).mean()

def compute_rsi(close, window=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return round(float((100 - (100 / (1 + rs))).iloc[-1]), 2)

def analyze_ticker(ticker: str, df: pd.DataFrame) -> dict:
    close, high, low, n = df["Close"].dropna(), df["High"].dropna(), df["Low"].dropna(), len(df["Close"].dropna())
    if n < 2: return {"ticker": ticker, "error": "veri_yok"}
    
    result = {"ticker": ticker, "last_price": round(float(close.iloc[-1]), 2), "days_available": n}
    
    # Volatilite
    if n >= MIN_DAYS["vol"]:
        log_ret = np.log(close / close.shift(1)).dropna()
        result["annual_vol_pct"] = round(log_ret.std() * np.sqrt(252 if n >= 252 else n) * 100, 2)
    
    # RSI
    if n >= MIN_DAYS["rsi"]:
        result["rsi"] = compute_rsi(close)
        result["rsi_signal"] = "🔴 Aşırı Alım" if result["rsi"] >= 70 else "🟢 Aşırı Satım" if result["rsi"] <= 30 else "🟡 Nötr"
    
    # EMA-200
    if n >= MIN_DAYS["ema200"]:
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        result["ema200"], result["trend"] = round(float(ema200), 2), ("📈 YUKARI" if close.iloc[-1] > ema200 else "📉 AŞAĞI")
        result["trend_pct"] = round((float(close.iloc[-1]) - ema200) / ema200 * 100, 2)
        
    # ATR & Momentum
    if n >= MIN_DAYS["atr"]: result["atr_pct"] = round(float(compute_atr(high, low, close).iloc[-1]) / float(close.iloc[-1]) * 100, 2)
    if n > MIN_DAYS["momentum"]: result["momentum_1m_pct"] = round((float(close.iloc[-1]) / float(close.iloc[-22]) - 1) * 100, 2)
    
    return result

def compute_action(r: dict) -> str:
    trend_up = "YUKARI" in r.get("trend", "")
    rsi = r.get("rsi")
    vol = r.get("annual_vol_pct")
    if rsi is None: return "⏳ Yetersiz Veri"
    if rsi > 70 and trend_up: return "🔴 KAR AL"
    if trend_up and rsi < 60 and (vol is None or vol < VOL_LOW_THRESHOLD): return "🟢 EKLE"
    return "⚪ NÖTR" if rsi >= 60 else "🟡 TUT"

def build_allocation_section(portfolio: dict, results: list) -> str:
    """Mevcut portföy dağılımını hesaplar ve Markdown tablosu döner."""
    # Fiyat haritası: analiz sonuçlarından al
    price_map = {r["ticker"]: r.get("last_price", 0.0) for r in results if "error" not in r}

    rows = []
    for ticker, lots in portfolio.items():
        price = price_map.get(ticker, 0.0)
        value = lots * price
        target = TARGET_WEIGHTS.get(ticker)
        rows.append({"ticker": ticker, "lots": lots, "price": price, "value": value, "target": target})

    total_value = sum(r["value"] for r in rows) or 1.0  # sıfıra bölme önlemi

    md = "\n## 💼 Portföy Dağılımı\n\n"
    md += f"> **Toplam Portföy Değeri:** ${total_value:,.2f}\n\n"
    md += "| Hisse | Lot | Fiyat | Değer ($) | Mevcut % | Hedef % | Sapma |\n"
    md += "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |\n"

    for r in sorted(rows, key=lambda x: x["value"], reverse=True):
        current_pct = r["value"] / total_value * 100
        target_pct  = r["target"]
        if target_pct is not None:
            deviation = current_pct - target_pct
            dev_str   = f"{'🔺' if deviation > 2 else '🔻' if deviation < -2 else '✅'} {deviation:+.1f}%"
            tgt_str   = f"%{target_pct:.1f}"
        else:
            dev_str = "—"
            tgt_str = "—"
        price_str = f"${r['price']:.2f}" if r["price"] else "—"
        md += (
            f"| **{r['ticker']}** | {r['lots']:.2f} | {price_str} | "
            f"${r['value']:,.2f} | %{current_pct:.2f} | {tgt_str} | {dev_str} |\n"
        )
    return md


def build_report(results: list, portfolio: dict | None = None) -> str:
    md = "# 📊 Strateji Motoru Raporu\n\n"

    # ── Bölüm 1: Portföy Dağılımı ────────────────────────────────────────────
    if portfolio:
        md += build_allocation_section(portfolio, results)

    # ── Bölüm 2: Teknik Analiz Tablosu ───────────────────────────────────────
    md += "\n## 📈 Teknik Analiz\n\n"
    md += "| Hisse | Fiyat | EMA-200 | Vol% | RSI | Aksiyon |\n"
    md += "| :--- | ---: | ---: | ---: | ---: | ---: |\n"
    for r in results:
        ticker = r.get("ticker", "?")
        if "error" in r:
            md += f"| **{ticker}** | — | — | — | — | ⚠️ {r['error']} |\n"
            continue
        action = compute_action(r)
        display_ticker = f"🟢 **{ticker}**" if action == "🟢 EKLE" else f"**{ticker}**"
        vol = r.get("annual_vol_pct")
        vol_str = f"**`%{vol:.2f}`**" if vol is not None and vol > VOL_LOW_THRESHOLD else (f"%{vol:.2f}" if vol is not None else "—")
        md += f"| {display_ticker} | ${r.get('last_price', 0):.2f} | {_fmt(r.get('ema200'), '.2f', '$')} | {vol_str} | {r.get('rsi', '—')} | **{action}** |\n"
    return md

def _fmt(val, fmt=".1f", prefix=""): return f"{prefix}{val:{fmt}}" if val is not None else "—"

def _resolve_ticker_level(raw: pd.DataFrame, tickers: list) -> int:
    """yfinance versiyonuna göre MultiIndex level'ını otomatik tespit eder."""
    if not isinstance(raw.columns, pd.MultiIndex):
        return -1  # tek ticker, MultiIndex yok
    sample = tickers[0]
    if sample in raw.columns.get_level_values(1):
        return 1   # yeni yfinance: (Price, Ticker)
    if sample in raw.columns.get_level_values(0):
        return 0   # eski yfinance: (Ticker, Price)
    log.warning("MultiIndex level tespit edilemedi, level=1 deneniyor.")
    return 1

def main():
    # ── 1. Portföy yükle ──────────────────────────────────────────────────────
    portfolio = get_portfolio()
    if not portfolio:
        log.error(
            "Portföy boş — olası nedenler:\n"
            "  • SHEET_URL yanlış veya erişilemiyor\n"
            "  • 'hisse' / 'lot' sütunu yok ya da tüm lot değerleri 0"
        )
        return

    # ── 2. Geçersiz ticker'ları ayır ──────────────────────────────────────────
    invalid_pre = [t for t in portfolio if t in KNOWN_INVALID_TICKERS]
    tickers     = [t for t in portfolio if t not in KNOWN_INVALID_TICKERS]
    if invalid_pre:
        log.warning(f"Atlanan geçersiz ticker'lar: {invalid_pre}")
    if not tickers:
        log.error("Geçerli ticker kalmadı.")
        return

    # ── 3. yfinance veri çek ──────────────────────────────────────────────────
    log.info(f"İndiriliyor: {tickers}")
    raw = yf.download(tickers, period=PERIOD, auto_adjust=True, progress=False)

    # Tek ticker edge case: MultiIndex oluşturmak için sarmalama
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw = pd.concat({tickers[0]: raw}, axis=1).swaplevel(axis=1)

    ticker_level = _resolve_ticker_level(raw, tickers)

    # ── 4. Analiz ─────────────────────────────────────────────────────────────
    results = [{"ticker": t, "error": "geçersiz_ticker"} for t in invalid_pre]

    for t in tickers:
        try:
            if ticker_level >= 0:
                ticker_df = raw.xs(t, axis=1, level=ticker_level)
            else:
                ticker_df = raw
            if ticker_df["Close"].dropna().empty:
                log.warning(f"{t}: Veri boş (delist veya geçersiz sembol?).")
                results.append({"ticker": t, "error": "veri_yok"})
                continue
            results.append(analyze_ticker(t, ticker_df))
        except Exception as e:
            log.error(f"{t} analiz hatası: {e}")
            results.append({"ticker": t, "error": str(e)})

    # ── 5. Rapor yaz ──────────────────────────────────────────────────────────
    md = build_report(results, portfolio=portfolio)
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)
    log.info("Analiz tamamlandı.")

if __name__ == "__main__":
    main()
