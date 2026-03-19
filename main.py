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
    os.makedirs(config.log_dir, exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    setup_logging(log_prefix="stock_analysis", log_dir=config.log_dir)
    
    logger = logging.getLogger(__name__)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--stocks', type=str)
    args, unknown = parser.parse_known_args()
    
    stock_codes = [canonical_stock_code(c) for c in args.stocks.split(',')] if args.stocks else config.stock_list
    
    logger.info(f"🚀 Analiz Başlıyor: {len(stock_codes)} Hisse")
    
    try:
        pipeline = StockAnalysisPipeline(config=config, query_id=uuid.uuid4().hex, max_workers=3)
        results = pipeline.run(stock_codes=stock_codes, send_notification=True)
        
        now = datetime.now().strftime('%d-%m-%Y %H:%M')
        full_content = f"## 📈 Karar Panosu Özet ({now})\n\n"
        
        if results:
            # Notifier üzerinden tabloyu oluştur
            full_content += pipeline.notifier.generate_aggregate_report(results, "simple")
        else:
            full_content += "⚠️ Analiz edilecek hisse bulunamadı veya veri çekilemedi."

        with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
            f.write(full_content)
            
        logger.info("✅ Rapor başarıyla kaydedildi.")
    except Exception as e:
        logger.error(f"❌ Analiz sırasında hata: {str(e)}")
        raise e

if __name__ == "__main__":
    sys.exit(main())
