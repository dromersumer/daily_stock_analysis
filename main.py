# -*- coding: utf-8 -*-
import os, argparse, logging, sys, uuid, requests
from datetime import datetime
from src.config import setup_env, get_config
from src.core.pipeline import StockAnalysisPipeline

def main():
    setup_env()
    config = get_config()
    os.makedirs("reports", exist_ok=True)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--stocks', type=str)
    args, _ = parser.parse_known_args()
    
    stock_input = args.stocks if args.stocks else os.getenv("STOCK_LIST", "")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]

    # yfinance için oturum maskeleme
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'})
    
    pipeline = StockAnalysisPipeline(config=config, query_id=uuid.uuid4().hex, max_workers=1)
    results = pipeline.run(stock_codes=stock_codes, send_notification=False)
    
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
    
    if results:
        report += "| Hisse | Öneri | Puan | Lynch Potansiyel | Risk Faktörü |\n"
        report += "| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            clean_name = r.name.replace("股票", "").strip()
            if not clean_name or "Unknown" in clean_name: clean_name = r.code.split('.')[0]
            lynch = r.dashboard.get('lynch_metrics', {}) if r.dashboard else {}
            report += f"| **{clean_name}** | {r.get_emoji()} {r.operation_advice} | {r.sentiment_score} | {lynch.get('potential', 'Bilinmiyor')} | {r.risk_warning[:30]}... |\n"
        
        report += "\n---\n### 🔍 Analiz Detayları\n"
        for r in results:
            clean_name = r.name.replace("股票", "").strip() or r.code
            report += f"#### 🔹 {clean_name}\n- **Lynch Notu:** {r.buy_reason}\n- **Risk:** {r.risk_warning}\n\n"
    else:
        report += "⚠️ Veri çekilemedi. Lütfen `STOCK_LIST` değişkenini (Örn: `ASELS.IS,ASTOR.IS`) kontrol edin."

    with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
        f.write(report)
    return 0

if __name__ == "__main__":
    sys.exit(main())
