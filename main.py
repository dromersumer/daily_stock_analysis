# -*- coding: utf-8 -*-
import os, argparse, logging, sys, json, time
from datetime import datetime
from curl_cffi import requests as cur_requests
from src.config import setup_env, get_config
from src.logging_config import setup_logging
from src.analyzer import GeminiAnalyzer

def fetch_stock_data(code, session):
    """Yahoo Finance API'den curl_cffi ile gizli veri çekme"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&period1={int(time.time())-604800}&period2={int(time.time())}"
    # Yahoo'yu Chrome olduğumuza ikna ediyoruz
    res = session.get(url, impersonate="chrome")
    if res.status_code != 200:
        return None
    
    data = res.json()
    result = data.get('chart', {}).get('result', [{}])[0]
    meta = result.get('meta', {})
    indicators = result.get('indicators', {}).get('quote', [{}])[0]
    
    if not meta or not indicators.get('close'):
        return None
        
    return {
        'code': code,
        'stock_name': meta.get('symbol', code),
        'today': {
            'close': round(indicators['close'][-1], 2),
            'pct_chg': round(((indicators['close'][-1] - indicators['close'][-2]) / indicators['close'][-2]) * 100, 2) if len(indicators['close']) > 1 else 0
        },
        'realtime': {
            'pe_ratio': 'N/A', # Ham API'de bu veri farklı uç noktadadır
            'market_cap': 'N/A'
        }
    }

def main():
    setup_env()
    config = get_config()
    os.makedirs("reports", exist_ok=True)
    setup_logging(log_prefix="stock_analysis", log_dir=config.log_dir)
    logger = logging.getLogger(__name__)
    
    stock_input = os.getenv("STOCK_LIST", "ASELS.IS,ASTOR.IS,THYAO.IS")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]

    # Gizli Oturum Başlat
    session = cur_requests.Session()
    analyzer = GeminiAnalyzer()
    results = []
    errors = []

    logger.info(f"🚀 Gizli Tünel Aktif. Analiz Ediliyor: {stock_codes}")

    for code in stock_codes:
        try:
            data = fetch_stock_data(code, session)
            if data:
                logger.info(f"🧠 AI Analiz Ediyor: {code}")
                res = analyzer.analyze(data)
                if res: results.append(res)
            else:
                errors.append(f"**{code}**: Veri çekme barajı aşılamadı.")
            time.sleep(2) # IP güvenliği için mola
        except Exception as e:
            errors.append(f"**{code}**: Beklenmedik hata ({str(e)[:50]})")

    # --- TÜRKÇE RAPOR ---
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
    
    if results:
        report += "| Hisse | Öneri | Puan | Lynch Potansiyel | Temel Risk |\n"
        report += "| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            report += f"| **{r.name}** | {r.get_emoji()} {r.operation_advice} | {r.sentiment_score} | {r.dashboard.get('lynch_metrics',{}).get('potential','Bilinmiyor')} | {r.risk_warning[:30]}... |\n"
        
        report += "\n---\n### 🔍 Peter Lynch Analiz Detayları\n"
        for r in results:
            report += f"#### 🔹 {r.name} ({r.code})\n- **Strateji:** {r.buy_reason}\n- **Kritik Risk:** {r.risk_warning}\n\n"
    
    if errors:
        report += "\n---\n### ⚠️ Notlar\n" + "\n".join([f"- {err}" for err in errors])

    with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
        f.write(report)
    return 0

if __name__ == "__main__":
    sys.exit(main())
