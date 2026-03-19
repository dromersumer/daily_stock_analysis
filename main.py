# -*- coding: utf-8 -*-
import os, argparse, logging, sys, uuid, requests, time
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
    
    # Liste temizliği ve kontrolü
    stock_input = args.stocks if args.stocks else os.getenv("STOCK_LIST", "ASELS.IS,ASTOR.IS")
    # Virgül, boşluk veya yeni satır ile ayrılmış listeleri temizle
    stock_codes = [s.strip().upper() for s in stock_input.replace('\n', ',').split(',') if s.strip()]

    # Yahoo Finance için oturum maskeleme
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    
    logger.info(f"🚀 Analiz Başlıyor: {stock_codes}")
    
    analyzer = GeminiAnalyzer()
    results = []
    errors = []

    for code in stock_codes:
        try:
            logger.info(f"🔍 {code} verisi çekiliyor...")
            ticker = yf.Ticker(code, session=session)
            # En son veriyi almak için 1 aylık veri isteyelim (daha stabil)
            hist = ticker.history(period="1mo")
            
            if hist.empty:
                logger.warning(f"⚠️ {code} verisi boş döndü.")
                errors.append(f"**{code}**: Veri bulunamadı (YFinance Boş).")
                continue

            info = ticker.info
            context = {
                'code': code,
                'stock_name': info.get('longName', code),
                'today': {
                    'close': round(hist['Close'].iloc[-1], 2),
                    'pct_chg': round(((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100, 2)
                },
                'realtime': {'pe_ratio': info.get('trailingPE', 'N/A')}
            }
            
            res = analyzer.analyze(context)
            if res: results.append(res)
            # IP engeli yememek için her hisse arasında kısa bir mola
            time.sleep(1) 

        except Exception as e:
            logger.error(f"❌ {code} hatası: {e}")
            errors.append(f"**{code}**: Sistem hatası ({str(e)[:50]}...)")

    # --- TÜRKÇE RAPOR ---
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
    
    if results:
        report += "| Hisse | Öneri | Puan | Lynch PEG | Risk Faktörü |\n"
        report += "| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            lynch = r.dashboard.get('lynch_metrics', {}) if r.dashboard else {}
            report += f"| **{r.name}** | {r.get_emoji()} {r.operation_advice} | {r.sentiment_score} | {lynch.get('potential', 'N/A')} | {r.risk_warning[:35]}... |\n"
        
        report += "\n---\n### 🔍 Detaylı Analiz Notları\n"
        for r in results:
            report += f"#### 🔹 {r.name} ({r.code})\n"
            report += f"- **Analiz:** {r.buy_reason}\n- **Risk:** {r.risk_warning}\n\n"
    
    if errors:
        report += "\n---\n### ⚠️ Veri Çekme Sorunları\n"
        report += "Bazı hisselerde veri çekilemedi:\n"
        for err in errors:
            report += f"- {err}\n"
        report += "\n*Not: Bu durum genellikle Yahoo Finance'in GitHub IP'lerini engellemesinden kaynaklanır. Lütfen 15-20 dakika sonra tekrar deneyin.*"

    with open(os.path.join("reports", "rapor.md"), "w", encoding="utf-8") as f:
        f.write(report)
    return 0

if __name__ == "__main__":
    sys.exit(main())
