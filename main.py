# -*- coding: utf-8 -*-
import os, sys, json, time, argparse
from datetime import datetime
from curl_cffi import requests as cur_requests
import litellm
from json_repair import repair_json

# --- 1. VERİ MODELİ ---
class AnalysisResult:
    def __init__(self, code, name, score=50, advice="Gözlem", summary="", reason="", risk="", peg="N/A"):
        self.code, self.name, self.score, self.advice = code, name, score, advice
        self.summary, self.reason, self.risk, self.peg = summary, reason, risk, peg
    def get_emoji(self):
        return {'Al': '🟢', 'Güçlü Al': '💚', 'Tut': '🟡', 'Sat': '🔴', 'Gözlem': '⚪'}.get(self.advice, '⚪')

# --- 2. VERİ ÇEKME MOTORU (YAHOO BYPASS + FILTRE) ---
def fetch_stock_data(code, session):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=7d"
        res = session.get(url, impersonate="chrome")
        if res.status_code != 200: return None
        data = res.json()
        result = data['chart']['result'][0]
        # None (boş) değerleri temizleyerek float hatasını önlüyoruz
        raw_prices = result['indicators']['quote'][0]['close']
        prices = [p for p in raw_prices if p is not None]
        
        if len(prices) < 2: return None
        return {
            'code': code,
            'name': result['meta'].get('symbol', code),
            'price': round(prices[-1], 2),
            'change': round(((prices[-1] - prices[-2]) / prices[-2]) * 100, 2)
        }
    except: return None

# --- 3. AI ANALİZÖRÜ (YEDEKLİ MODEL SİSTEMİ) ---
def analyze_stock(data, api_key):
    prompt = f"Hisse: {data['name']}\nFiyat: {data['price']}\nDeğişim: %{data['change']}\nPeter Lynch tarzı analiz et."
    
    # 404 hatasını aşmak için sırayla denenecek modeller
    models_to_try = [
        "gemini/gemini-1.5-flash",
        "gemini/gemini-1.5-flash-latest",
        "gemini/gemini-pro"
    ]
    
    for model_name in models_to_try:
        try:
            res = litellm.completion(
                model=model_name,
                api_key=api_key,
                messages=[
                    {"role": "system", "content": "Sen Peter Lynch'sin. Türkçe yanıtla. SADECE JSON ver: {\"score\":80,\"advice\":\"Al\",\"summary\":\"...\",\"reason\":\"...\",\"risk\":\"...\",\"peg\":\"0.5\"}"},
                    {"role": "user", "content": prompt}
                ],
                timeout=30
            )
            raw = res.choices[0].message.content.replace('```json', '').replace('```', '').strip()
            d = json.loads(repair_json(raw))
            return AnalysisResult(
                data['code'], data['name'], 
                d.get('score', 50), d.get('advice', 'Gözlem'), 
                d.get('summary', ''), d.get('reason', ''), 
                d.get('risk', ''), d.get('peg', 'N/A')
            )
        except Exception as e:
            # Eğer son model de başarısız olursa hatayı döndür
            if model_name == models_to_try[-1]:
                return AnalysisResult(data['code'], data['name'], reason=f"AI Hatası: {str(e)[:40]}")
            continue # Bir sonraki modeli dene

# --- 4. ANA AKIŞ ---
def main():
    os.makedirs("reports", exist_ok=True)
    api_key = os.getenv("GEMINI_API_KEY")
    # Değişken boşsa buradaki liste devreye girer
    stock_input = os.getenv("STOCK_LIST", "ASELS.IS,ASTOR.IS,THYAO.IS,TUPRS.IS")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    
    session = cur_requests.Session()
    results = []
    
    print(f"🚀 Dr. Ömer için {len(stock_codes)} hisse analiz ediliyor...")
    for code in stock_codes:
        data = fetch_stock_data(code, session)
        if data:
            res = analyze_stock(data, api_key)
            if res: results.append(res)
        time.sleep(1) # Güvenlik molası

    # --- RAPOR OLUŞTURMA ---
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
    
    if results:
        report += "| Hisse | Öneri | Puan | Lynch PEG | Temel Risk |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            report += f"| **{r.name}** | {r.get_emoji()} {r.advice} | {r.score} | {r.peg} | {r.risk[:30]}... |\n"
        
        report += "\n---\n### 🔍 Peter Lynch Analiz Detayları\n"
        for r in results:
            report += f"#### 🔹 {r.name} ({r.code})\n"
            report += f"- **Strateji:** {r.reason}\n"
            report += f"- **Analiz Özeti:** {r.summary}\n"
            report += f"- **Kritik Risk:** {r.risk}\n\n---\n"
    else:
        report += "⚠️ Veri çekilemedi veya AI modellerine ulaşılamadı. Lütfen API anahtarını kontrol edin."

    with open("reports/rapor.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("✅ Analiz başarıyla tamamlandı ve rapor oluşturuldu.")

if __name__ == "__main__":
    main()
