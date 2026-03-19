# -*- coding: utf-8 -*-
import os, argparse, logging, sys, uuid
from datetime import datetime
import yfinance as yf
from src.config import setup_env, get_config
from src.logging_config import setup_logging
from src.analyzer import GeminiAnalyzer

def main():
    setup_env()
    config = get_config()
    os.makedirs("reports", exist_ok=True)
    setup_logging(log_prefix="stock_analysis", log_dir=config.log_dir)
    logger = logging.getLogger(__name__)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--stocks', type=str)
    args, _ = parser.parse_known_args()
    
    stock_input = args.stocks if args.stocks else os.getenv("STOCK_LIST", "ASELS.IS,ASTOR.IS")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]

    logger.info(f"🚀 Analiz Başlıyor: {stock_codes}")
    
    analyzer = GeminiAnalyzer()
    results = []

    for code in stock_codes:
        try:
            logger.info(f"🔍 Veri çekiliyor: {code}")
            ticker = yf.Ticker(code)
            hist = ticker.history(period="5d")
            info = ticker.info
            
            if hist.empty:
                logger.warning(f"⚠️ {code} verisi boş.")
                continue

            context = {
                'code': code,
                'stock_name': info.get('longName', code),
                'today': {'close': hist['Close'].iloc[-1]},
                'realtime': {'pe_ratio': info.get('trailingPE', 'N/A')}
            }
            
            # AI Analizi
            res = analyzer.analyze(context)
            if res:
                results.append(res)

        except Exception as e:
            logger.error(f"❌ {code} hatası: {e}")

    # --- TÜRKÇE RAPOR ---
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
    
    if results:
        report += "| Hisse | Öneri | Puan | Lynch Potansiyel | Temel Risk |\n"
        report += "| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            lynch = r.dashboard.get('lynch_metrics', {}) if r.dashboard else {}
            report += f"| **{r.name}** | {r.get_emoji()} {r.operation_advice} | {r.sentiment_score} | {lynch.get('potential', 'Bilinmiyor')} | {r.risk_warning[:35]}... |\n"
        
        report += "\n---\n### 🔍 Peter Lynch Analiz Detayları\n"
        for r in results:
            report += f"#### 🔹 {r.name} ({r.code})\n"
            report += f"- **Strateji:** {r.buy_reason}\n"
            report += f"- **Risk:** {r.risk_warning}\n"
            report += f"- **Özet:** {r.analysis_summary}\n\n---\n"
    else:
        report += "⚠️ Veri çekilemedi veya AI analizi başarısız oldu."

    with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
        f.write(report)
    return 0

if __name__ == "__main__":
    sys.exit(main())
