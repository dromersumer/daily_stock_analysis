# -*- coding: utf-8 -*-
import os, argparse, logging, sys, uuid
from datetime import datetime
from src.config import setup_env, get_config, Config
from src.logging_config import setup_logging
from src.core.pipeline import StockAnalysisPipeline
from data_provider.base import canonical_stock_code

setup_env()
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stocks', type=str)
    parser.add_argument('--no-market-review', action='store_true', default=True)
    parser.add_argument('--force-run', action='store_true', default=True)
    args = parser.parse_args()
    
    config = get_config()
    setup_logging(log_prefix="stock_analysis", log_dir=config.log_dir)
    
    stock_codes = [canonical_stock_code(c) for c in args.stocks.split(',')] if args.stocks else config.stock_list
    
    logger.info(f"🚀 Analiz Başlıyor: {len(stock_codes)} Hisse")
    
    pipeline = StockAnalysisPipeline(config=config, query_id=uuid.uuid4().hex)
    results = pipeline.run(stock_codes=stock_codes, send_notification=True)
    
    # Raporu Markdown olarak kaydet
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    full_content = f"# 🚀 Hisse Karar Panosu ({now})\n\n"
    if results:
        full_content += pipeline.notifier.generate_aggregate_report(results, "simple")
    
    os.makedirs("reports", exist_ok=True)
    with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
        f.write(full_content)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
