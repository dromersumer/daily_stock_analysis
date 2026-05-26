# -*- coding: utf-8 -*-
"""
Apex Terminal — Quant Engine v25.4
Bloomberg-grade autonomous portfolio manager for BIST & US markets.
Architecture: Data → Analytics (ATR/Vol/Risk Parity) → AI Layer → GitHub Summary
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

# ── Google GenAI ────────────────────────────────────────────────────────────
try:
    from google import genai as google_genai
    from google.genai import types as genai_types
    _GENAI_AVAILABLE = True
except ImportError:
    google_genai = None
    _GENAI_AVAILABLE = False

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ApexTerminal")

# ── Ortam Değişkenleri ───────────────────────────────────────────────────────
PORTFOLIO_TYPE   = os.getenv("PORTFOLIO_TYPE", "ABD").upper()
START_CAPITAL    = float(os.getenv("PORTFOLIO_CAPITAL", "10000" if PORTFOLIO_TYPE == "ABD" else "100000"))
MAX_PORTFOLIO_SIZE   = int(os.getenv("MAX_PORTFOLIO_SIZE", "19"))
MAX_WEIGHT_PER_STOCK = float(os.getenv("MAX_WEIGHT", "0.35"))
USE_AI           = os.getenv("USE_AI", "false").lower() == "true"
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
CURRENCY         = "$" if PORTFOLIO_TYPE == "ABD" else "₺"

# Mevcut portföy — ortam değişkeninden JSON olarak okunabilir
# Örnek: CURRENT_PORTFOLIO='{"NVDA": 5, "AAPL": 10}'
_raw_portfolio = os.getenv("CURRENT_PORTFOLIO", "{}")
try:
    CURRENT_PORTFOLIO: dict[str, int] = json.loads(_raw_portfolio)
except json.JSONDecodeError:
    CURRENT_PORTFOLIO = {}

# ── Teknik Analiz ────────────────────────────────────────────────────────────

def get_technical(df: pd.DataFrame) -> Optional[dict]:
    """
    EMA-200, ATR-14, Yıllıklandırılmış Volatilite, RSI-14 hesaplar.
    Yetersiz veri varsa None döner.
    """
    if len(df) < 201:
        return None

    close = df["Close"].astype(float)
    high  = df["High"].astype(float)
    low   = df["Low"].astype(float)

    # EMA-200
    ema200 = close.ewm(span=200, adjust=False).mean()

    # ATR-14  (Wilder's smoothing — rolling avg burada doğru)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(window=14).mean()

    # Yıllıklandırılmış Volatilite (20 günlük)
    daily_ret = close.pct_change()
    vol = daily_ret.rolling(20).std() * math.sqrt(252)

    # RSI-14
    delta    = daily_ret.dropna()
    gain     = delta.clip(lower=0).rolling(14).mean()
    loss     = (-delta.clip(upper=0)).rolling(14).mean()
    rs       = gain / loss.replace(0, np.nan)
    rsi_full = 100 - (100 / (1 + rs))
    # RSI'yı orijinal index'e geri hizala
    rsi = rsi_full.reindex(close.index)

    last = df.iloc[-1]
    last_close = float(close.iloc[-1])
    last_ema   = float(ema200.iloc[-1])
    last_atr   = float(atr.iloc[-1])
    last_vol   = float(vol.iloc[-1])
    last_rsi   = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0

    # Piyasa rejimi
    regime = "TREND" if last_close > last_ema else "WEAK"

    # Momentum: son 20 günlük getiri
    momentum = float(close.pct_change(20).iloc[-1]) if len(close) > 20 else 0.0

    return {
        "price":    round(last_close, 4),
        "ema200":   round(last_ema, 4),
        "atr":      round(last_atr, 4),
        "vol":      round(last_vol, 4),
        "rsi":      round(last_rsi, 2),
        "momentum": round(momentum, 4),
        "regime":   regime,
        "last_date": str(df.index[-1].date()),
    }


# ── Portföy Optimizasyonu ────────────────────────────────────────────────────

def compute_risk_parity_weights(techs: dict[str, dict]) -> dict[str, float]:
    """
    Inverse-Volatility Risk Parity:
    Her hissenin ağırlığı volatilitesiyle ters orantılıdır.
    Eşit risk katkısı (ERC) yaklaşımı.
    """
    inv_vol = {s: 1.0 / max(t["vol"], 0.01) for s, t in techs.items()}
    total   = sum(inv_vol.values())
    return {s: v / total for s, v in inv_vol.items()}


def apply_weight_cap_and_renormalize(
    weights: dict[str, float],
    cap: float = MAX_WEIGHT_PER_STOCK,
) -> dict[str, float]:
    """
    Maksimum ağırlık kapağı uygular ve yeniden normalize eder.
    Konverjan olana dek iteratif çalışır.
    """
    w = dict(weights)
    for _ in range(50):          # maksimum 50 iterasyon
        capped    = {s: min(v, cap) for s, v in w.items()}
        overflow  = sum(v - cap for v in w.values() if v > cap)
        below_cap = {s for s, v in w.items() if v < cap}

        if overflow < 1e-9 or not below_cap:
            return capped

        total_below = sum(capped[s] for s in below_cap)
        for s in below_cap:
            capped[s] += overflow * (capped[s] / total_below)

        # Normalize
        total = sum(capped.values())
        w = {s: v / total for s, v in capped.items()}

    return w


def score_stock(tech: dict) -> float:
    """
    Çok faktörlü hisse skorlama:
    - Trend rejimi   : 40 puan
    - Düşük volatilite: 25 puan
    - RSI momentum   : 20 puan (40–70 arası sağlıklı bölge)
    - Fiyat momentumu: 15 puan
    """
    score = 0.0
    if tech["regime"] == "TREND":
        score += 40.0

    # Volatilite skoru: V < 0.20 → tam puan, V > 0.80 → sıfır
    vol_score = max(0.0, 1.0 - (tech["vol"] / 0.80)) * 25.0
    score += vol_score

    # RSI skoru: 40–70 → sağlıklı momentum bölgesi
    rsi = tech["rsi"]
    if 40 <= rsi <= 70:
        score += 20.0
    elif rsi < 40:
        score += rsi / 40 * 10.0   # aşırı satım: kısmi puan
    else:
        score += max(0.0, (100 - rsi) / 30 * 10.0)  # aşırı alım: düşen puan

    # Momentum skoru: pozitif momentum → 15 puan, negatif → 0
    mom = tech["momentum"]
    score += min(15.0, max(0.0, mom * 100))

    return round(score, 2)


# ── AI Katmanı ───────────────────────────────────────────────────────────────

def get_ai_comments(
    portfolio_summary: str,
    api_key: str,
) -> str:
    """
    Gemini 2.0 Flash ile Türkçe piyasa yorumu üretir.
    Fail-safe: API hatasında boş string döner, sistem durmaz.
    """
    if not _GENAI_AVAILABLE or not api_key:
        log.warning("AI katmanı devre dışı — API key eksik veya kütüphane yüklü değil.")
        return ""

    try:
        client = google_genai.Client(api_key=api_key)
        prompt = f"""
Sen Bloomberg Terminal'ın kıdemli portföy stratejistisin.
Aşağıdaki kantitatif portföy analizini inceleyerek profesyonel, 
Türkçe bir yatırım özeti yaz (maksimum 250 kelime).

Odaklan:
1. Portföyün genel risk profili (volatilite bazlı)
2. Öne çıkan TREND hisseleri ve fırsatlar
3. Dikkat edilmesi gereken riskler (yüksek vol, zayıf momentum)
4. Kısa bir aksiyon önerisi

VERİ:
{portfolio_summary}

Not: Bu finansal tavsiye değildir, yalnızca kantitatif analiz özetidir.
"""
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=600,
            ),
        )
        return response.text.strip()

    except Exception as exc:
        log.error(f"Gemini API hatası: {exc} — Fail-safe moduna geçildi.")
        return ""


# ── Rapor Üretimi ────────────────────────────────────────────────────────────

def build_report(
    target: list[dict],
    techs: dict[str, dict],
    orders: list[dict],
    ai_comment: str,
    run_ts: str,
) -> str:
    """GitHub Actions Markdown özeti üretir."""

    header = f"""# 🏦 Apex Terminal v25.4 — {PORTFOLIO_TYPE} Portföyü
> **Çalışma Zamanı:** {run_ts} UTC | **Sermaye:** {CURRENCY}{START_CAPITAL:,.0f}

---

### 📚 Terimler Sözlüğü
| Terim | Açıklama |
| :---- | :------- |
| **V** | Yıllıklandırılmış fiyat oynaklığı (σ × √252). Yüksek V = yüksek risk. |
| **ATR** | Average True Range. Dinamik stop-loss mesafesinin temelidir. |
| **Dinamik Stop** | `Fiyat − ATR × (2.0 + V×2.0)`. V arttıkça stop mesafesi otomatik genişler. |
| **Risk Parity** | Her hissenin eşit risk katkısı için ağırlıklar inverse-vol ile belirlenir. |
| **TREND / WEAK** | Fiyatın 200-günlük EMA üzerinde / altında olma durumu. |
| **RSI** | 14 günlük Relative Strength Index. 40–70 sağlıklı momentum bölgesi. |

---
"""

    # İşlem önerileri
    order_section = "### 🔄 İŞLEM ÖNERİLERİ\n"
    if orders:
        order_section += "| İşlem | Hisse | Lot | Fiyat | Detay |\n| :--- | :--- | ---: | ---: | :--- |\n"
        for o in orders:
            emoji = "🟢 AL" if o["action"] == "BUY" else ("🔴 SAT" if o["action"] == "SELL" else "⚪ TUT")
            order_section += f"| {emoji} | **{o['code']}** | {o['lot']} | {CURRENCY}{o['price']:.2f} | {o['detail']} |\n"
    else:
        order_section += "> ℹ️ Mevcut portföy bilgisi sağlanmadı — rebalancing analizi atlandı.\n"

    order_section += "\n"

    # Hedef portföy tablosu
    portfolio_section = "### 🎯 HEDEF PORTFÖY & DİNAMİK STOP\n"
    portfolio_section += "| Hisse | Ağırlık | Lot | Giriş | Stop | V | ATR | RSI | Rejim |\n"
    portfolio_section += "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |\n"

    for t in target:
        regime_icon = "📈" if t["regime"] == "TREND" else "📉"
        portfolio_section += (
            f"| **{t['code']}** "
            f"| {t['weight']*100:.1f}% "
            f"| {t['lot']} "
            f"| {CURRENCY}{t['price']:.2f} "
            f"| {CURRENCY}{t['stop']:.2f} "
            f"| {t['vol']:.2f} "
            f"| {t['atr']:.2f} "
            f"| {t['rsi']:.0f} "
            f"| {regime_icon} {t['regime']} |\n"
        )

    portfolio_section += "\n"

    # Elenen hisseler
    failed_section = ""
    failed = [s for s in techs if s not in {t["code"] for t in target}]
    if failed:
        failed_section = f"### ⚠️ Portföye Alınamayan Hisseler\n"
        failed_section += "| Hisse | Skor | Neden |\n| :--- | ---: | :--- |\n"
        for s in failed:
            t = techs.get(s, {})
            reason = "Düşük skor" if t else "Veri yetersiz"
            sc = score_stock(t) if t else 0
            failed_section += f"| {s} | {sc:.1f} | {reason} |\n"
        failed_section += "\n"

    # AI yorum
    ai_section = ""
    if ai_comment:
        ai_section = f"### 🤖 Gemini AI Piyasa Analizi\n> {ai_comment.replace(chr(10), chr(10)+'> ')}\n\n"
    else:
        ai_section = "> 🔇 AI analizi bu çalışmada devre dışı veya kullanılamadı (fail-safe mod).\n\n"

    # Footer
    footer = (
        "---\n"
        f"*Apex Terminal v25.4 | {run_ts} | "
        "Bu rapor otomatik üretilmiştir. Finansal tavsiye niteliği taşımaz.*\n"
    )

    return header + order_section + portfolio_section + failed_section + ai_section + footer


# ── Ana Motor ────────────────────────────────────────────────────────────────

def main():
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Apex Terminal başlatıldı — {PORTFOLIO_TYPE} | {run_ts}")

    # Hisse listesi
    stock_input = os.getenv(
        "STOCK_LIST",
        "VOO,SCHD,QQQM,SPUS,VXUS,O,WPC,SMH,NVDA,AVGO,GOOG,CAT,ASPI",
    )
    stocks = [s.strip().upper() for s in stock_input.split(",") if s.strip()]
    log.info(f"Analiz edilecek {len(stocks)} hisse: {stocks}")

    # ── Veri İndirme ─────────────────────────────────────────────────────────
    log.info("yfinance'ten 2 yıllık veri çekiliyor...")
    try:
        raw = yf.download(
            tickers=stocks,
            period="2y",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        log.error(f"Veri indirme hatası: {exc}")
        sys.exit(1)

    if raw is None or raw.empty:
        log.error("Boş veri geldi. Çıkılıyor.")
        sys.exit(1)

    # yfinance'in multi-ticker çıktısı: (ticker, field) MultiIndex
    # Tek ticker indirilirse farklı format döner — normalize et
    if len(stocks) == 1:
        raw.columns = pd.MultiIndex.from_product([stocks, raw.columns])

    # ── Teknik Analiz ─────────────────────────────────────────────────────────
    techs: dict[str, dict] = {}
    scores: dict[str, float] = {}

    for s in stocks:
        if s not in raw.columns.get_level_values(0):
            log.warning(f"{s}: veri bulunamadı, atlandı.")
            continue

        df = raw[s].copy().dropna(how="all")

        # Sütun isimlerini normalize et (bazen lowercase gelir)
        df.columns = [c.capitalize() for c in df.columns]
        required_cols = {"Close", "High", "Low", "Open", "Volume"}
        if not required_cols.issubset(df.columns):
            log.warning(f"{s}: eksik sütunlar {required_cols - set(df.columns)}, atlandı.")
            continue

        tech = get_technical(df)
        if tech is None:
            log.warning(f"{s}: yetersiz veri (<201 gün), atlandı.")
            continue

        techs[s] = tech
        scores[s] = score_stock(tech)
        log.info(f"{s}: Skor={scores[s]:.1f} | Rejim={tech['regime']} | V={tech['vol']:.2f} | RSI={tech['rsi']:.1f}")

    if not techs:
        log.error("Hiçbir hisse için teknik veri üretilemedi.")
        sys.exit(1)

    # ── Hisse Seçimi ──────────────────────────────────────────────────────────
    selected = sorted(scores, key=scores.__getitem__, reverse=True)[:MAX_PORTFOLIO_SIZE]
    log.info(f"Seçilen {len(selected)} hisse: {selected}")

    selected_techs = {s: techs[s] for s in selected}

    # ── Risk Parity Ağırlıkları ───────────────────────────────────────────────
    raw_weights = compute_risk_parity_weights(selected_techs)
    weights     = apply_weight_cap_and_renormalize(raw_weights, cap=MAX_WEIGHT_PER_STOCK)

    # ── Pozisyon & Stop Hesaplama ─────────────────────────────────────────────
    target: list[dict] = []
    for s in selected:
        t     = techs[s]
        w     = weights[s]
        price = t["price"]
        vol   = t["vol"]
        atr   = t["atr"]

        # Dinamik stop: ATR çarpanı volatiliteyle genişler
        stop_multiplier = 2.0 + (vol * 2.0)
        stop_val = round(price - (atr * stop_multiplier), 4)

        # Lot hesaplama
        allocation = START_CAPITAL * w
        lot = math.floor(allocation / price) if price > 0 else 0

        target.append({
            "code":    s,
            "weight":  round(w, 4),
            "lot":     lot,
            "price":   price,
            "stop":    stop_val,
            "vol":     vol,
            "atr":     atr,
            "rsi":     t["rsi"],
            "regime":  t["regime"],
        })

    # ── Rebalancing (mevcut portföy varsa) ───────────────────────────────────
    orders: list[dict] = []
    if CURRENT_PORTFOLIO:
        target_map = {t["code"]: t["lot"] for t in target}
        all_codes  = set(CURRENT_PORTFOLIO) | set(target_map)
        for code in all_codes:
            current_lot = CURRENT_PORTFOLIO.get(code, 0)
            target_lot  = target_map.get(code, 0)
            diff = target_lot - current_lot
            price = techs.get(code, {}).get("price", 0)
            if diff > 0:
                orders.append({"action": "BUY",  "code": code, "lot": diff,
                               "price": price, "detail": f"+{diff} lot ekle"})
            elif diff < 0:
                orders.append({"action": "SELL", "code": code, "lot": abs(diff),
                               "price": price, "detail": f"{diff} lot azalt"})

    # ── AI Analizi ────────────────────────────────────────────────────────────
    ai_comment = ""
    if USE_AI and GEMINI_API_KEY:
        summary_for_ai = json.dumps(
            [{"code": t["code"], "weight": f"{t['weight']*100:.1f}%",
              "vol": t["vol"], "rsi": t["rsi"], "regime": t["regime"],
              "stop_distance_pct": round((t["price"] - t["stop"]) / t["price"] * 100, 2)}
             for t in target],
            ensure_ascii=False,
            indent=2,
        )
        ai_comment = get_ai_comments(summary_for_ai, GEMINI_API_KEY)

    # ── Rapor Üret ve GitHub Summary'e Yaz ───────────────────────────────────
    report_md = build_report(
        target=target,
        techs=techs,
        orders=orders,
        ai_comment=ai_comment,
        run_ts=run_ts,
    )

    # GitHub Actions Step Summary
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        try:
            with open(summary_file, "w", encoding="utf-8") as f:
                f.write(report_md)
            log.info("Rapor GitHub Actions Summary'e yazıldı.")
        except IOError as exc:
            log.error(f"Summary dosyasına yazılamadı: {exc}")
    else:
        # Lokal çalıştırmada stdout'a bas
        print("\n" + "═" * 80)
        print(report_md)
        print("═" * 80)

    log.info("Apex Terminal başarıyla tamamlandı.")


if __name__ == "__main__":
    main()
