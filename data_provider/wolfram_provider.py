# -*- coding: utf-8 -*-
import wolframalpha
import os

# Analitik değeri olmayan veya raporu gereksiz kalabalıklaştıran başlıklar
EXCLUDED_PODS = {"Input interpretation", "Image", "Definition", "Summary"}

class WolframValuationProvider:
    def __init__(self):
        # API Key temizliği ve güvenli yükleme
        raw_key = os.getenv("WOLFRAM_ALPHA_APPID") or ""
        self.api_key = raw_key.strip() or None
        self.client = wolframalpha.Client(self.api_key) if self.api_key else None
        
        # In-memory önbellek (Sadece başarılı sorguları saklar)
        self._cache = {}

    def get_stock_valuation(self, ticker):
        if not self.client:
            return "Hata: Wolfram API anahtarı (AppID) bulunamadı."

        # Önce önbellekten bak (Daha önceki başarılı sorgular için)
        if ticker in self._cache:
            return self._cache[ticker]

        # Wolfram'ın finans veritabanıyla en iyi eşleşen sorgu formatı
        query = f"{ticker} stock price PE ratio intrinsic value debt-to-equity"
        
        try:
            # DÜZELTME: 10 saniyelik zaman aşımı (timeout) eklendi. 
            # GitHub Actions job'ının donmasını engeller.
            res = self.client.query(query, timeout=10)
            
            pods = getattr(res, 'pods', None) or []
            results = []
            
            for pod in pods:
                # Analitik değeri olmayan pod başlıklarını filtrele
                if pod.title in EXCLUDED_PODS:
                    continue
                    
                for subpod in pod.subpods:
                    # Boşluk ve None kontrolü (getattr ile güvenli erişim)
                    content = getattr(subpod, 'plaintext', None)
                    if content and content.strip():
                        results.append(f"{pod.title}: {content.strip()}")
            
            if not results:
                result = f"Veri bulunamadı: {ticker} için Wolfram kütüphanesi henüz güncellenmemiş olabilir."
            else:
                result = "\n".join(results)
                # DÜZELTME: Yalnızca başarılı ve veri içeren sonuçları önbelleğe al
                self._cache[ticker] = result
            
            return result

        except Exception as e:
            # DÜZELTME: Hata durumunda önbelleğe yazmadan çık. 
            # Böylece bir sonraki döngüde/run'da tekrar deneme şansı olur.
            print(f"[WOLFRAM HATA] {ticker}: {e}")
            return f"Hata: Wolfram sorgusu başarısız — {ticker}"
