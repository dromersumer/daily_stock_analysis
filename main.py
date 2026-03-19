# -*- coding: utf-8 -*-
import os, argparse, logging, sys, uuid, requests
from datetime import datetime
import yfinance as yf
from src.config import setup_env, get_config
from src.logging_config import setup_logging
from src.core.pipeline import StockAnalysisPipeline

# --- YAHOO FINANCE ENGELİNİ AŞAN MASKELEME ---
def session_setup():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    return session

def main():
    setup_env()
    config = get_config()
    os.makedirs("reports", exist_ok=True)
    setup_logging(log_prefix="stock_analysis", log_dir=config.log_dir)
    logger = logging.getLogger(__name__)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--stocks', type=str)
    args, _ = parser.parse_known_args()
    
    # Liste temizliği ve kontrolü
    stock_input = args.stocks if args.stocks else os.getenv("STOCK_LIST", "")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]

    if not stock_codes:
        logger.error("Hisse listesi boş!")
        return 1

    logger.info(f"🚀 Analiz Başlıyor: {stock_codes}")
    
    try:
        # yfinance için oturumu global olarak ayarla
        custom_session = session_setup()
        
        pipeline = StockAnalysisPipeline(config=config, query_id=uuid.uuid4().hex, max_workers=1)
        
        # Analiz sürecini başlat
        results = pipeline.run(stock_codes=stock_codes, send_notification=False)
        
        now = datetime.now().strftime('%d-%m-%Y %H:%M')
        report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
        
        if results:
            report += "| Hisse | Öneri | Puan | Lynch Potansiyel | Risk Faktörü |\n"
            report += "| :--- | :--- | :--- | :--- | :--- |\n"
            
            for r in results:
                # İsim temizliği
                clean_name = r.name.replace("股票", "").strip()
                if not clean_name or "Unknown" in clean_name:
                    clean_name = r.code.split('.')[0]
                
                lynch = r.dashboard.get('lynch_metrics', {}) if r.dashboard else {}
                report += f"| **{clean_name}** | {r.get_emoji()} {r.operation_advice} | {r.sentiment_score} | {lynch.get('potential', 'Bilinmiyor')} | {r.risk_warning[:35]}... |\n"
            
            report += "\n---\n### 🔍 Peter Lynch Analiz Detayları\n"
            for r in results:
                clean_name = r.name.replace("股票", "").strip() or r.code
                report += f"#### 🔹 {clean_name}\n"
                report += f"- **Lynch Notu:** {r.buy_reason}\n"
                report += f"- **Kritik Risk:** {r.risk_warning}\n"
                report += f"- **Genel Özet:** {r.analysis_summary}\n\n"
        else:
            report += "### ⚠️ VERİ ÇEKİLEMEYE DEVAM EDİYOR\n"
            report += "Yahoo Finance, GitHub sunucularını hala engelliyor. \n\n"
            report += "**Çözüm Önerisi:** \n"
            report += "1. Birkaç dakika bekleyip tekrar 'Run workflow' yapın.\n"
            report += f"2. Şu kodları analiz etmeye çalıştık: `{stock_codes}`. Kodların doğruluğunu (Örn: THYAO.IS) teyit edin."

        with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
            f.write(report)
            
        logger.info("✅ İşlem tamamlandı.")
    except Exception as e:
        logger.error(f"❌ Hata: {str(e)}")
        raise e

if __name__ == "__main__":
    sys.exit(main())
