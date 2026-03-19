# -*- coding: utf-8 -*-
import os, argparse, logging, sys, uuid
from datetime import datetime
from src.config import setup_env, get_config
from src.logging_config import setup_logging
from src.core.pipeline import StockAnalysisPipeline

def main():
    setup_env()
    config = get_config()
    os.makedirs("reports", exist_ok=True)
    setup_logging(log_prefix="stock_analysis", log_dir=config.log_dir)
    logger = logging.getLogger(__name__)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--stocks', type=str)
    args, _ = parser.parse_known_args()
    
    # Liste temizliği
    stock_list_raw = args.stocks if args.stocks else os.getenv("STOCK_LIST", "")
    stock_codes = [s.strip().upper() for s in stock_list_raw.split(',') if s.strip()]

    logger.info(f"🚀 Analiz Başlıyor: {stock_codes}")
    
    try:
        pipeline = StockAnalysisPipeline(config=config, query_id=uuid.uuid4().hex, max_workers=1)
        # Analiz sürecini başlat
        results = pipeline.run(stock_codes=stock_codes, send_notification=False)
        
        now = datetime.now().strftime('%d-%m-%Y %H:%M')
        report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
        
        if results:
            report += "| Hisse | Öneri | Puan | Lynch Potansiyel | Risk Faktörü |\n"
            report += "| :--- | :--- | :--- | :--- | :--- |\n"
            
            for r in results:
                clean_name = r.name.replace("股票", "").strip()
                if not clean_name or "Unknown" in clean_name:
                    clean_name = r.code.split('.')[0]
                
                lynch = r.dashboard.get('lynch_metrics', {}) if r.dashboard else {}
                report += f"| **{clean_name}** | {r.get_emoji()} {r.operation_advice} | {r.sentiment_score} | {lynch.get('potential', 'Bilinmiyor')} | {r.risk_warning[:35]}... |\n"
            
            report += "\n---\n### 🔍 Detaylı Analiz Notları\n"
            for r in results:
                clean_name = r.name.replace("股票", "").strip() or r.code
                report += f"#### 🔹 {clean_name}\n"
                report += f"- **Analiz:** {r.buy_reason}\n"
                report += f"- **Kritik Risk:** {r.risk_warning}\n\n"
        else:
            report += "⚠️ **KRİTİK UYARI:** yfinance üzerinden veri çekilemedi.\n"
            report += "Bu durum genellikle Yahoo Finance'in GitHub sunucularını geçici olarak engellemesinden kaynaklanır.\n"
            report += "Lütfen 15 dakika sonra tekrar deneyin veya hisse kodlarını (Örn: ASELS.IS) kontrol edin."

        with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
            f.write(report)
            
        logger.info("✅ Rapor oluşturuldu.")
    except Exception as e:
        logger.error(f"❌ Hata: {str(e)}")
        raise e

if __name__ == "__main__":
    sys.exit(main())
