# -*- coding: utf-8 -*-
# main.py — Apex Terminal v35.0 (Dinamik Google Drive API Destekli)
import io, json, logging, os, sys, numpy as np, pandas as pd, yfinance as yf
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ApexTerminal")

# ── Ayarlar & Sabitler ────────────────────────────────────────────────────────
FOLDER_ID = "13GFB_k1Y5toNGKCmj3EUKLO5Gdp7T9Zp"
FILE_NAME_OMER = "ABDPortfoy.csv"
FILE_NAME_OZLEM = "ABDPortfoy_Ozlem.csv"

PERIOD, ATR_WINDOW, ATR_MULTIPLIER = "2y", 14, 3.0  # Volatilite koruması aktif
TARGET_WEIGHTS = {
    "VOO": 15.0, "SCHD": 10.0, "QQQM": 5.0, "SPUS": 5.0, 
    "VXUS": 15.0, "O": 7.5, "WPC": 7.5, "SMH": 7.5, 
    "AIS": 7.5, "NASA": 7.5
}

def get_gdrive_service():
    try:
        key_json = os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        if not key_json:
            log.error("HATA: GDRIVE_SERVICE_ACCOUNT_KEY bulunamadı!")
            return None
        info = json.loads(key_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        log.error(f"Google Drive API servisi başlatılamadı: {e}")
        return None

def download_csv_from_gdrive(service, folder_id: str, filename: str) -> dict:
    try:
        query = f"'{folder_id}' in parents and name = '{filename}' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get("files", [])
        
        if not items:
            log.warning(f"Klasörde '{filename}' isimli dosya bulunamadı.")
            return {}
            
        file_id = items[0]["id"]
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            _, done = downloader.next_chunk()
            
        fh.seek(0)
        df = pd.read_csv(io.StringIO(fh.read().decode("utf-8-sig")))
        df.columns = df.columns.str.strip().str.lower()
        df = df.dropna(subset=["hisse"])
        df["hisse"] = df["hisse"].astype(str).str.strip().str.upper().str.split(":").str[-1]
        df["lot"]   = df["lot"].astype(str).str.replace(",", ".", regex=False).pipe(pd.to_numeric, errors="coerce").fillna(0)
        return dict(zip(df["hisse"], df[df["lot"] > 0]["lot"]))
    except Exception as e:
        log.error(f"Google Drive'dan dosya indirilirken hata oluştu ({filename}): {e}")
        return {}

def analyze_ticker(ticker: str, df: pd.DataFrame) -> dict:
    close, high, low = df["Close"].dropna(), df["High"].dropna(), df["Low"].dropna()
    n = len(close)
    if n < 30: return {"ticker": ticker, "error": "veri_yetersiz"}
    
    prev_close = float(close.iloc[-2])
    last_p     = float(close.iloc[-1])
    
    pct_change = ((last_p - prev_close) / prev_close) * 100
    if pct_change > 0:
        change_str = f"🟢 %+{pct_change:.2f}"
    elif pct_change < 0:
        change_str = f"🔴 %{pct_change:.2f}"
    else:
        change_str = f"⚫ %0.00"
        
    ema50  = close.ewm(span=50, adjust=False).mean().iloc[-1]
    ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1] if n >= 200 else None
    
    tr = pd.concat([high-low, (high-close.shift(1)).abs(), (low-close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/ATR_WINDOW, adjust=False).mean().iloc[-1]
    
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = round(float((100 - (100 / (1 + gain / loss.replace(0, np.nan)))).iloc[-1]), 2)
    
    return {
        "ticker": ticker, 
        "prev_close": round(prev_close, 2),
        "last_price": round(last_p, 2), 
        "change_str": change_str,
        "rsi": rsi,
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

def build_user_report(user_name: str, portfolio: dict, global_results: dict) -> str:
    price_map = {t: r.get("last_price", 0.0) for t, r in global_results.items() if "error" not in r}
    total_val = sum(lots * price_map.get(t, 0) for t, lots in portfolio.items()) or 1.0
    
    md = f"## 💼 Portföy Dağılımı - {user_name}\n| Hisse | Lot | Değer ($) | Mevcut % | Hedef % |\n| :--- | ---: | ---: | ---: | ---: |\n"
    for t, lots in portfolio.items():
        val = lots * price_map.get(t, 0)
        md += f"| **{t}** | {lots} | ${val:,.2f} | %{(val/total_val*100):.1f} | {'%'+str(TARGET_WEIGHTS.get(t)) if TARGET_WEIGHTS.get(t) else '—'} |\n"
    
    md += f"\n> 💰 **{user_name} Toplam Portföy:** ${total_val:,.2f}\n\n"
    md += f"### 📈 Teknik Analiz & Stop Loss - {user_name}\n| Hisse | Önceki Kapanış Fiyat | Son Fiyat | Fiyat Artış/Azalış% | Stop Loss | Trend | RSI | Aksiyon |\n| :--- | ---: | ---: | :---: | ---: | :--- | ---: | ---: |\n"
    
    for t in portfolio.keys():
        r = global_results.get(t, {})
        if not r or "error" in r:
            err_msg = r.get("error", "veri_yok") if r else "veri_yok"
            md += f"| **{t}** | — | — | — | — | — | — | ⚠️ {err_msg} |\n"
            continue
        stop_alert = "🚨" if r['last_price'] < (r['stop_loss'] * 1.03) else ""
        md += f"| **{t}** | ${r['prev_close']:.2f} | ${r['last_price']:.2f} | {r['change_str']} | ${r['stop_loss']} {stop_alert} | {r.get('trend_state', 'N/A')} | {r.get('rsi', '—')} | **{compute_action(r)}** |\n"
    
    return md

def main():
    service = get_gdrive_service()
    if not service:
        sys.exit(1)
        
    # Dosyaları link bağımsız, sadece isimleriyle klasörden çekiyoruz
    p_omer = download_csv_from_gdrive(service, FOLDER_ID, FILE_NAME_OMER)
    p_ozlem = download_csv_from_gdrive(service, FOLDER_ID, FILE_NAME_OZLEM)
    
    if not p_omer and not p_ozlem:
        log.error("Her iki portföy de boş veya Drive'dan yüklenemedi.")
        sys.exit(0)
        
    all_tickers = list(set(list(p_omer.keys()) + list(p_ozlem.keys())))
    
    raw = yf.download(all_tickers, period=PERIOD, auto_adjust=True, progress=False)
    level = 1 if isinstance(raw.columns, pd.MultiIndex) and all_tickers[0] in raw.columns.get_level_values(1) else (0 if isinstance(raw.columns, pd.MultiIndex) else -1)
    
    global_results = {}
    for t in all_tickers:
        try:
            df = raw.xs(t, axis=1, level=level) if level >= 0 else raw
            global_results[t] = analyze_ticker(t, df)
        except Exception as e:
            global_results[t] = {"ticker": t, "error": str(e)}
            
    final_md = "# 🚀 Apex Terminal Ortak Rapor Paneli\n"
    final_md += f"> 🛡️ **Sistem Parametresi (Mevcut Risk):** {ATR_MULTIPLIER}x ATR Stop\n\n---\n\n"
    
    if p_omer:
        final_md += build_user_report("Ömer", p_omer, global_results) + "\n\n---\n\n"
    if p_ozlem:
        final_md += build_user_report("Özlem", p_ozlem, global_results)
        
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.getenv("GITHUB_STEP_SUMMARY"), "w", encoding="utf-8") as f: f.write(final_md)
    print(final_md)
    
    sys.exit(0)

if __name__ == "__main__":
    main()
