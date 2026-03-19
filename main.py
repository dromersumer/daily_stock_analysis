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
    
    # Hisse listesini temiz alıyoruz (Örn: ASELS.IS)
    if args.stocks:
        stock_codes = [s.strip().upper() for s in args.stocks.split(',')]
    else:
        stock_codes = config.stock_list

    logger.info(f"🚀 Analiz Başlıyor: {stock_codes}")
    
    try:
        pipeline = StockAnalysisPipeline(config=config, query_id=uuid.uuid4().hex, max_workers=2)
        # Analizi çalıştır
        results = pipeline.run(stock_codes=stock_codes, send_notification=False)
        
        now = datetime.now().strftime('%d-%m-%Y %H:%M')
        report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
        
        if results:
            report += "| Hisse | Öneri | Puan | Lynch Potansiyel | Risk Faktörü |\n"
            report += "| :--- | :--- | :--- | :--- | :--- |\n"
            
            for r in results:
                # İsim temizliği
                clean_name = r.name.replace("股票", "").strip()
                if clean_name == f"股票{r.code}" or not clean_name:
                    clean_name = r.code.split('.')[0]
                
                lynch = r.dashboard.get('lynch_metrics', {}) if r.dashboard else {}
                advice = r.operation_advice
                if "观望" in advice: advice = "Gözlem"
                
                report += f"| **{clean_name}** | {r.get_emoji()} {advice} | {r.sentiment_score} | {lynch.get('potential', 'Bilinmiyor')} | {r.risk_warning[:35]}... |\n"
            
            report += "\n---\n### 🔍 Peter Lynch Analiz Detayları\n"
            for r in results:
                clean_name = r.name.replace("股票", "").strip()
                if clean_name == f"股票{r.code}" or not clean_name:
                    clean_name = r.code.split('.')[0]
                
                report += f"#### 🔹 {clean_name} ({r.code})\n"
                report += f"- **Lynch Stratejisi:** {r.buy_reason if r.buy_reason else 'Veri yetersizliği nedeniyle genel yorum yapıldı.'}\n"
                report += f"- **Kritik Uyarı:** {r.risk_warning if r.risk_warning else 'Veri bekleniyor.'}\n"
                report += f"- **Genel Özet:** {r.analysis_summary if r.analysis_summary else 'Hisse teknik verileri çekilemedi.'}\n\n"
        else:
            report += "⚠️ Veri çekilemedi. yfinance bağlantısını kontrol edin."

        with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
            f.write(report)
            
        logger.info("✅ Rapor başarıyla oluşturuldu.")
    except Exception as e:
        logger.error(f"❌ Hata: {str(e)}")
        raise e

if __name__ == "__main__":
    sys.exit(main())
