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

# SHEET_URL önce env'den okunur; fallback olarak hardcoded URL kullanılır.
# GitHub Secret'ta SHEET_URL tanımlanırsa hardcoded değer devre dışı kalır.
_SHEET_URL_FALLBACK = (
    "https://docs.google.com/spreadsheets/d/"
    "1_bi1N5770a3BsPXreq_wHlU4reBQxVvUqd_tcdEaZPk/export?format=csv"
)
SHEET_URL = os.getenv("SHEET_URL", _SHEET_URL_FALLBACK)

PERIOD = "2y"
ATR_WINDOW = 14

# Her gösterge için minimum gün eşiği
MIN_DAYS = {
    "vol":      21,   # ~1 ay
    "rsi":      14,   # Wilder periyodu
    "momentum": 22,   # 1 aylık momentum
    "ema200":  200,   # EMA-200
    "atr":      14,
}


# Bilinen geçersiz / yfinance'ta veri döndürmeyen ticker'lar.
# Portföyde bulunursa yf.download'a gönderilmez, raporda ⚠️ olarak işaretlenir.
KNOWN_INVALID_TICKERS: set[str] = set(
    os.getenv("KNOWN_INVALID_TICKERS", "").upper().split(",")
) - {""}   # boş string'i temizle


def get_portfolio() -> dict:
    """
    Google Sheets'ten portföyü çeker.
    Hata durumunda boş dict döndürür ve sebebini loglar.
    """
    url = SHEET_URL
    if not url:
        log.error(
            "SHEET_URL tanımlı değil. "
            "GitHub Secret olarak ekleyin veya kodu düzenleyin."
        )
        return {}
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.content.decode("utf-8-sig")))
        df.columns = df.columns.str.strip().str.lower()
        df = df.dropna(subset=["hisse"])
        df["hisse"] = df["hisse"].astype(str).str.strip().str.upper().str.split(":").str[-1]
        df["lot"] = (
            df["lot"].astype(str).str.replace(",", ".", regex=False)
            .pipe(pd.to_numeric, errors="coerce").fillna(0)
        )
        df = df[df["lot"] > 0]
        return dict(zip(df["hisse"], df["lot"]))
    except requests.exceptions.Timeout:
        log.error("Portföy yüklenemedi: Google Sheets bağlantısı zaman aşımına uğradı (15s).")
        return {}
    except requests.exceptions.HTTPError as e:
        log.error(f"Portföy yüklenemedi: HTTP {e.response.status_code} — Sheet gizli veya URL yanlış olabilir.")
        return {}
    except Exception as e:
        log.error(f"Portföy yüklenemedi: {e}")
        return {}


def compute_ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's ATR (smoothed true range)."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False).mean()


def compute_rsi(close: pd.Series, window: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def analyze_ticker(ticker: str, df: pd.DataFrame) -> dict:
    """
    Katmanlı eşik sistemi: her gösterge kendi minimum gün sayısını kontrol eder.
    1 aydan yeni bir hisse bile kısmen analiz edilebilir.
    """
    close = df["Close"].dropna()
    high  = df["High"].dropna()
    low   = df["Low"].dropna()
    n     = len(close)

    if n < 2:
        log.warning(f"{ticker}: Hiç veri yok.")
        return {"ticker": ticker, "error": "veri_yok"}

    result = {
        "ticker": ticker,
        "last_price": round(float(close.iloc[-1]), 2),
        "days_available": n,
    }

    # ── Yıllık Volatilite (min 21 gün) ──────────────────────────────────────
    if n >= MIN_DAYS["vol"]:
        log_ret = np.log(close / close.shift(1)).dropna()
        annualize_factor = 252 if n >= 252 else n   # kısa geçmişte tahmini
        result["annual_vol_pct"] = round(log_ret.std() * np.sqrt(annualize_factor) * 100, 2)
        result["vol_note"] = None if n >= 252 else f"⚠️ {n}g veriyle tahmin"
    else:
        result["annual_vol_pct"] = None
        result["vol_note"] = f"⚠️ Yetersiz veri ({n} gün)"

    # ── RSI (min 14 gün) ─────────────────────────────────────────────────────
    if n >= MIN_DAYS["rsi"]:
        rsi = compute_rsi(close)
        result["rsi"] = rsi
        if rsi >= 70:
            result["rsi_signal"] = "🔴 Aşırı Alım"
        elif rsi <= 30:
            result["rsi_signal"] = "🟢 Aşırı Satım"
        else:
            result["rsi_signal"] = "🟡 Nötr"
    else:
        result["rsi"] = None
        result["rsi_signal"] = f"⏳ {MIN_DAYS['rsi'] - n}g eksik"

    # ── EMA-200 / Trend (min 200 gün) ────────────────────────────────────────
    if n >= MIN_DAYS["ema200"]:
        ema200 = compute_ema(close, 200).iloc[-1]
        result["ema200"] = round(float(ema200), 2)
        result["trend"] = "📈 YUKARI" if close.iloc[-1] > ema200 else "📉 AŞAĞI"
        result["trend_pct"] = round((float(close.iloc[-1]) - float(ema200)) / float(ema200) * 100, 2)
    else:
        result["ema200"] = None
        result["trend"] = f"⏳ EMA-200 için {MIN_DAYS['ema200'] - n}g eksik"
        result["trend_pct"] = None

    # ── ATR (min 14 gün) ─────────────────────────────────────────────────────
    if n >= MIN_DAYS["atr"]:
        atr_val = compute_atr(high, low, close, ATR_WINDOW).iloc[-1]
        result["atr_pct"] = round(float(atr_val) / float(close.iloc[-1]) * 100, 2)
    else:
        result["atr_pct"] = None

    # ── Momentum 1M (min 22 gün) ─────────────────────────────────────────────
    if n > MIN_DAYS["momentum"]:
        result["momentum_1m_pct"] = round(
            (float(close.iloc[-1]) / float(close.iloc[-22]) - 1) * 100, 2
        )
    else:
        result["momentum_1m_pct"] = None

    return result


def _fmt(val, fmt=".1f", suffix="", prefix="") -> str:
    """None-safe formatter."""
    if val is None:
        return "—"
    return f"{prefix}{val:{fmt}}{suffix}"


# Volatilite eşiği: yıllık %30'un altı "düşük" kabul edilir
VOL_LOW_THRESHOLD = float(os.getenv("VOL_LOW_THRESHOLD", "30.0"))

# Sabit hedef ağırlıklar — burada tanımlanmayan ticker için sütun boş kalır
TARGET_WEIGHTS: dict[str, float] = {
    "VOO":  15.0,
    "SCHD": 10.0,
    "QQQM": 10.0,
    "VXUS": 15.0,
    "O":    15.0,
    "SMH":   7.5,
    "AIS":   7.5,
    "NASA":  7.5,
}


def compute_action(r: dict) -> str:
    """
    Mevcut göstergelere bakarak tek satırlık aksiyon önerisi üretir.
    Öncelik sırası: Kritik → Uyarı → Fırsat → Nötr
    Veri eksikse → ⏳ Yetersiz Veri
    """
    trend_up   = "YUKARI" in r.get("trend", "")
    trend_down = "AŞAĞI"  in r.get("trend", "")
    rsi        = r.get("rsi")
    vol        = r.get("annual_vol_pct")
    ema200     = r.get("ema200")
    price      = r.get("last_price")

    # Yeterli veri kontrolü
    has_ema   = ema200 is not None and price is not None
    has_rsi   = rsi is not None
    has_vol   = vol is not None

    if not has_rsi:
        return "⏳ Yetersiz Veri"

    # ── Kural 1: Aşırı Isınma ──────────────────────────────────────────────
    # RSI > 70 + Trend YUKARI → Kar al
    if has_rsi and rsi > 70 and trend_up:
        return "🔴 KAR AL"

    # ── Kural 2: Çöküş Riski ───────────────────────────────────────────────
    # RSI > 70 + Trend AŞAĞI → Çift tehlike
    if has_rsi and rsi > 70 and trend_down:
        return "🔴 SAT / ÇIKIŞ"

    # ── Kural 3: Zayıflık İzleme ───────────────────────────────────────────
    # Fiyat EMA-200 altında + RSI < 40
    if has_ema and trend_down and rsi < 40:
        return "⚠️ İZLE"

    # ── Kural 4: Güçlü Fırsat ──────────────────────────────────────────────
    # Trend YUKARI + RSI < 60 + Volatilite Düşük
    vol_ok = (not has_vol) or (vol < VOL_LOW_THRESHOLD)
    if trend_up and has_rsi and rsi < 60 and vol_ok:
        return "🟢 EKLE"

    # ── Kural 5: Trend var ama RSI ılımlı ──────────────────────────────────
    if trend_up and has_rsi and 60 <= rsi <= 70:
        return "🟡 TUT"

    # ── Kural 6: EMA bilgisi yok ama RSI güçlü ─────────────────────────────
    if not has_ema and has_rsi and rsi < 60:
        return "🟡 İZLE (EMA yok)"

    return "⚪ NÖTR"


def build_report(results: list) -> str:
    md = "# 📊 Strateji Motoru Raporu\n\n"
    md += "| Hisse | Fiyat | Veri (gün) | EMA-200 | Trend | Yıllık Vol% | ATR% | RSI | RSI Sinyali | Mom 1M% | Hedef Ağırlık% | **Aksiyon** |\n"
    md += "| :--- | ---: | ---: | ---: | :--- | ---: | ---: | ---: | :--- | ---: | ---: | :---: |\n"

    for r in results:
        ticker = r.get("ticker", "?")
        target_w = TARGET_WEIGHTS.get(ticker)
        target_w_str = f"%{target_w:.1f}" if target_w is not None else "—"

        if "error" in r:
            md += f"| **{ticker}** | — | — | — | ⚠️ {r['error']} | — | — | — | — | — | {target_w_str} | — |\n"
            continue

        trend_str = r["trend"]
        if r["trend_pct"] is not None:
            trend_str += f" ({r['trend_pct']:+.1f}%)"

        vol_str = _fmt(r["annual_vol_pct"], ".2f", "%")
        if r.get("vol_note"):
            vol_str += f" {r['vol_note']}"

        action = compute_action(r)

        md += (
            f"| **{ticker}** "
            f"| ${r['last_price']} "
            f"| {r['days_available']} "
            f"| {_fmt(r['ema200'], '.2f', prefix='$')} "
            f"| {trend_str} "
            f"| {vol_str} "
            f"| {_fmt(r['atr_pct'], '.2f', '%')} "
            f"| {_fmt(r['rsi'], '.1f')} "
            f"| {r.get('rsi_signal', '—')} "
            f"| {_fmt(r['momentum_1m_pct'], '+.1f', '%')} "
            f"| {target_w_str} "
            f"| **{action}** |\n"
        )

    # ── Aksiyon Özeti ────────────────────────────────────────────────────────
    valid = [r for r in results if "error" not in r]
    action_groups = {
        "🟢 EKLE":         [],
        "🔴 KAR AL":       [],
        "🔴 SAT / ÇIKIŞ":  [],
        "⚠️ İZLE":         [],
        "🟡 TUT":          [],
    }
    for r in valid:
        a = compute_action(r)
        if a in action_groups:
            action_groups[a].append(r["ticker"])

    md += "\n### 📋 Aksiyon Özeti\n\n"
    for label, tickers_list in action_groups.items():
        if tickers_list:
            md += f"- **{label}:** {', '.join(f'`{t}`' for t in tickers_list)}\n"

    md += f"\n> ℹ️ *Volatilite eşiği: yıllık **%{VOL_LOW_THRESHOLD:.0f}** altı \"düşük\" kabul edilir. "
    md += f"`VOL_LOW_THRESHOLD` ortam değişkeniyle değiştirilebilir.*\n"

    # ── Kısa geçmişli varlık uyarıları ───────────────────────────────────────
    new_issues = [r for r in valid if r["days_available"] < MIN_DAYS["ema200"]]
    if new_issues:
        md += "\n> ℹ️ **Kısa Geçmişli Varlıklar:** "
        md += ", ".join(
            f"`{r['ticker']}` ({r['days_available']}g — EMA-200 için {MIN_DAYS['ema200'] - r['days_available']}g eksik)"
            for r in new_issues
        )
        md += "\n"

    return md


def _resolve_ticker_level(raw: pd.DataFrame, tickers: list) -> int:
    """
    yfinance MultiIndex formatı versiyona göre değişir:
      - Yeni (0.2.x): (Price, Ticker)  → ticker level=1
      - Eski         : (Ticker, Price)  → ticker level=0
    İlk ticker'ın hangi seviyede bulunduğunu kontrol ederek doğru level'ı döndürür.
    """
    if not isinstance(raw.columns, pd.MultiIndex):
        return -1  # tek ticker, MultiIndex yok
    sample = tickers[0]
    if sample in raw.columns.get_level_values(1):
        return 1
    if sample in raw.columns.get_level_values(0):
        return 0
    # Hiçbirinde bulunamazsa varsayılan olarak 1 dene
    log.warning("MultiIndex level tespit edilemedi, level=1 deneniyor.")
    return 1


def main():
    portfolio = get_portfolio()
    if not portfolio:
        log.error(
            "Portföy boş — olası nedenler:\n"
            "  • SHEET_URL tanımlı değil veya yanlış\n"
            "  • Google Sheets erişime kapalı (gizlilik ayarı)\n"
            "  • Tabloda 'hisse' / 'lot' sütunu yok ya da tüm lot değerleri 0"
        )
        return

    all_tickers = list(portfolio.keys())

    # ── Geçersiz ticker'ları ayır, yf.download'a gönderme ──────────────────
    invalid_pre = [t for t in all_tickers if t in KNOWN_INVALID_TICKERS]
    tickers     = [t for t in all_tickers if t not in KNOWN_INVALID_TICKERS]

    if invalid_pre:
        log.warning(f"Geçersiz/atlanan ticker'lar (KNOWN_INVALID_TICKERS): {invalid_pre}")

    if not tickers:
        log.error("Geçerli ticker kalmadı.")
        return

    log.info(f"Analiz edilecek: {tickers}")

    raw = yf.download(tickers, period=PERIOD, auto_adjust=True, progress=False)

    # ── Tek ticker edge case ────────────────────────────────────────────────
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw = pd.concat({tickers[0]: raw}, axis=1).swaplevel(axis=1)

    # ── MultiIndex level tespiti (versiyon bağımsız) ────────────────────────
    ticker_level = _resolve_ticker_level(raw, tickers)

    results = []
    missing = list(invalid_pre)  # geçersiz ticker'lar zaten eksik

    # Geçersiz ticker'ları da rapora ekle
    for t in invalid_pre:
        results.append({"ticker": t, "error": "geçersiz_ticker"})

    for t in tickers:
        try:
            if ticker_level >= 0:
                ticker_df = raw.xs(t, axis=1, level=ticker_level)
            else:
                ticker_df = raw
            if ticker_df["Close"].dropna().empty:
                log.warning(f"{t}: yfinance veri döndürmedi (delist veya geçersiz sembol?).")
                missing.append(t)
                results.append({"ticker": t, "error": "veri_yok"})
                continue
            results.append(analyze_ticker(t, ticker_df))
        except Exception as e:
            log.error(f"{t} analiz hatası: {e}")
            missing.append(t)
            results.append({"ticker": t, "error": str(e)})

    md = build_report(results)

    # Delist / veri yok uyarısı
    if missing:
        md += f"\n> ⚠️ **Fiyatı/verisi çekilemeyen varlıklar:** `{'`, `'.join(missing)}`\n"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)
    log.info("Strateji analizi tamamlandı.")

    return results


if __name__ == "__main__":
    main()
