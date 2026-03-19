# -*- coding: utf-8 -*-
import os, argparse, logging, sys, uuid
from datetime import datetime
from src.config import setup_env, get_config
from src.logging_config import setup_logging
from src.core.pipeline import StockAnalysisPipeline
from data_provider.base import canonical_stock_code

def main():
    setup_env()
    config = get_config()
    os.makedirs("reports", exist_ok=True)
    setup_logging(log_prefix="stock_analysis", log_dir=config.log_dir)
    
    logger = logging.getLogger(__name__)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--stocks', type=str)
    args, _ = parser.parse_known_args()
    
    # Hisseleri alırken .IS uzantısını koru
    stock_codes = [canonical_stock_code(c) for c in args.stocks.split(',')] if args.stocks else config.stock_list
    
    logger.info(f"🚀 Analiz Başlıyor: {len(stock_codes)} Hisse")
    
    try:
        pipeline = StockAnalysisPipeline(config=config, query_id=uuid.uuid4().hex, max_workers=2)
        # Bildirimleri False yapıyoruz çünkü raporu biz manuel hazırlayacağız
        results = pipeline.run(stock_codes=stock_codes, send_notification=False)
        
        now = datetime.now().strftime('%d-%m-%Y %H:%M')
        
        # --- TÜRKÇE MANUEL RAPOR TASARIMI ---
        report = f"## 📈 Dr. Ömer - Karar Panosu ({now})\n\n"
        
        if results:
            report += "| Hisse | Öneri | Puan | Lynch Notu | Temel Risk |\n"
            report += "| :--- | :--- | :--- | :--- | :--- |\n"
            
            for r in results:
                lynch = r.dashboard.get('lynch_metrics', {}) if r.dashboard else {}
                emoji = r.get_emoji()
                advice = r.operation_advice
                # Çince kalıntılarını burada da süzüyoruz
                if "观望" in advice: advice = "Gözlem"
                
                report += f"| **{r.name}** | {emoji} {advice} | {r.sentiment_score} | {lynch.get('potential', 'N/A')} | {r.risk_warning[:40]}... |\n"
            
            report += "\n---\n### 🔍 Peter Lynch Merceğinden Detaylar\n"
            for r in results:
                report += f"#### 🔹 {r.name} ({r.code})\n"
                report += f"- **Lynch Analizi:** {r.buy_reason}\n"
                report += f"- **Kritik Uyarı:** {r.risk_warning}\n"
                report += f"- **Özet:** {r.analysis_summary}\n\n"
        else:
            report += "⚠️ Hisse verileri çekilemedi. Lütfen hisse kodlarını (Örn: THYAO.IS) kontrol edin."

        with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
            f.write(report)
            
        logger.info("✅ Rapor başarıyla oluşturuldu.")
    except Exception as e:
        logger.error(f"❌ Kritik Hata: {str(e)}")
        raise e

if __name__ == "__main__":
    sys.exit(main())
