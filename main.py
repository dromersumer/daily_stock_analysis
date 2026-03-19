# -*- coding: utf-8 -*-
"""
===================================
Hisse Senedi Akıllı Analiz Sistemi
===================================
Dr. Ömer için Özelleştirilmiş Sürüm
"""
import os
from src.config import setup_env
setup_env()

import argparse
import logging
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

from data_provider.base import canonical_stock_code
from src.core.pipeline import StockAnalysisPipeline
from src.core.market_review import run_market_review
from src.config import get_config, Config
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)

def parse_arguments() -> argparse.Namespace:
    """Komut satırı argümanlarını ayrıştırır"""
    parser = argparse.ArgumentParser(description='Hisse Senedi Akıllı Analiz Sistemi')
    parser.add_argument('--debug', action='store_true', help='Detaylı log çıktısı')
    parser.add_argument('--dry-run', action='store_true', help='AI analizi yapmadan sadece veri çek')
    parser.add_argument('--stocks', type=str, help='Analiz edilecek hisse kodları (virgülle ayırın)')
    parser.add_argument('--no-notify', action='store_true', help='Bildirim gönderme')
    parser.add_argument('--workers', type=int, default=None, help='Eşzamanlı işlem sayısı')
    parser.add_argument('--market-review', action='store_true', help='Sadece genel piyasa özeti yap')
    parser.add_argument('--no-market-review', action='store_true', default=True, help='Genel piyasa özetini atla (Hisselere odaklan)')
    parser.add_argument('--force-run', action='store_true', default=True, help='Takvim kontrolünü atla ve çalıştır')
    return parser.parse_args()

def run_full_analysis(config: Config, args: argparse.Namespace, stock_codes: Optional[List[str]] = None):
    """Hisseler ve Piyasa Analiz Sürecini Yönetir"""
    try:
        if stock_codes is None:
            config.refresh_stock_list()
        
        effective_codes = stock_codes if stock_codes is not None else config.stock_list
        
        logger.info(f"🚀 Analiz Başlıyor... Toplam Hisse: {len(effective_codes)}")

        query_id = uuid.uuid4().hex
        pipeline = StockAnalysisPipeline(
            config=config,
            max_workers=args.workers,
            query_id=query_id,
            query_source="cli",
            save_context_snapshot=False
        )

        # 1. HİSSE ANALİZİ (Öncelikli)
        results = pipeline.run(
            stock_codes=effective_codes,
            dry_run=args.dry_run,
            send_notification=not args.no_notify,
            merge_notification=False
        )

        # 2. RAPOR OLUŞTURMA
        full_content = ""
        now = datetime.now().strftime('%d-%m-%Y %H:%M')
        
        if results:
            dashboard_content = pipeline.notifier.generate_aggregate_report(
                results,
                getattr(config, 'report_type', 'simple'),
            )
            full_content += f"# 🚀 Hisse Karar Panosu ({now})\n\n{dashboard_content}"
        else:
            full_content += f"# ⚠️ Uyarı\nSeçilen hisseler için veri çekilemedi veya analiz yapılamadı."

        # Raporu Dosyaya Yaz (Summary için)
        report_path = os.path.join("reports", f"analiz_raporu_{uuid.uuid4().hex[:6]}.md")
        os.makedirs("reports", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        
        logger.info(f"✅ Analiz tamamlandı. Rapor oluşturuldu: {report_path}")

    except Exception as e:
        logger.exception(f"❌ Analiz sürecinde hata: {e}")

def main() -> int:
    args = parse_arguments()
    config = get_config()
    setup_logging(log_prefix="stock_analysis", debug=args.debug, log_dir=config.log_dir)

    logger.info("=" * 60)
    logger.info("Hisse Senedi Analiz Sistemi Başlatıldı")
    logger.info("=" * 60)

    stock_codes = None
    if args.stocks:
        stock_codes = [canonical_stock_code(c) for c in args.stocks.split(',') if (c or "").strip()]

    # Doğrudan analizi çalıştır
    run_full_analysis(config, args, stock_codes)
    return 0

if __name__ == "__main__":
    sys.exit(main())
