# -*- coding: utf-8 -*-
import os, sys, json, time
from datetime import datetime
from curl_cffi import requests as cur_requests
import google.generativeai as genai
from json_repair import repair_json

# --- 1. VERİ MODELİ ---
class AnalysisResult:
    def __init__(self, code, name, score=50, advice="Gözlem", summary="", reason="", risk="", peg="N/A"):
        self.code, self.name, self.score, self.advice = code, name, score, advice
        self.summary, self.reason, self.risk, self.peg = summary, reason, risk, peg
    def get_emoji(self):
        return {'Al': '🟢', 'Güçlü Al': '💚', 'Tut': '🟡', 'Sat': '🔴', 'Gözlem': '⚪'}.get(self.advice, '⚪')

# --- 2. VERİ ÇEKME MOTORU (YAHOO BYPASS) ---
def fetch_stock_data(code, session):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=7d"
        res = session.get(url, impersonate="chrome")
        if res.status_code != 200: return None
        data = res.json()
        result = data['chart']['result'][0]
        prices = [p for p in result['indicators']['quote'][0]['close'] if p is not None]
        if len(prices) < 2: return None
        return {
            'code': code, 'name': result['meta'].get('symbol', code),
            'price': round(prices[-1], 2),
            'change': round(((prices[-1] - prices[-2]) / prices[-2]) * 100, 2)
        }
    except: return None

# --- 3. AKILLI AI ANALİZÖRÜ (DYNAMIC MODEL SELECTION) ---
def analyze_with_google(data, api_key):
    try:
        genai.configure(api_key=api_key)
        # Mevcut modelleri listele ve en iyisini seç
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        prefer_list = ['models/gemini-1.5-flash', 'models/gemini-1.5-flash-latest', 'models/gemini-pro']
        selected_model = next((p for p in prefer_list if p in available_models), available_models[0] if available_models else 'models/gemini-pro')

        model = genai.GenerativeModel(selected_model)
        prompt = f"""Hisse: {data['name']} ({data['code']}). Fiyat: {data['price']}, Değişim: %{data['change']}. 
        Peter Lynch tarzı analiz et. Türkçe yanıtla. SADECE JSON döndür:
        {{"score": 80, "advice": "Al/Tut/Sat", "summary": "...", "reason": "...", "risk": "...", "peg": "..."}}"""
        
        response = model.generate_content(prompt)
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        d = json.loads(repair_json(raw_text))
        
        return AnalysisResult(
            data['code'], data['name'], d.get('score', 50), d.get('advice', 'Gözlem'),
            d.get('summary', ''), d.get('reason', ''), d.get('risk', ''), d.get('peg', 'N/A')
        )
    except Exception as e:
        return AnalysisResult(data['code'], data['name'], reason=f"AI Hatası: {str(e)[:50]}")

# --- 4. ANA AKIŞ (HIZ SABİTLEYİCİ EKLENDİ) ---
def main():
    os.makedirs("reports", exist_ok=True)
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "TUPRS.IS,THYAO.IS,SISE.IS")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    
    session = cur_requests.Session()
    results = []
    
    print(f"🚀 Dr. Ömer için {len(stock_codes)} hisselik operasyon başlıyor...")
    
    for i, code in enumerate(stock_codes):
        # --- KRİTİK: Her 5 hissede bir 20 saniye mola (API Kotası Koruması) ---
        if i > 0 and i % 5 == 0:
            print(f"⏳ Kota dolmaması için 20 saniye mola veriliyor ({i}/{len(stock_codes)} tamamlandı)...")
            time.sleep(20)
            
        data = fetch_stock_data(code, session)
        if data:
            print(f"🧠 {code} analiz ediliyor...")
            res = analyze_with_google(data, api_key)
            if res: results.append(res)
        
        # Her hisse arasında standart 5 saniye bekleme (Yavaş ama güvenli)
        time.sleep(5)

    # Tarih formatı YYYY_MM_DD (Kronolojik sıralama için)
    date_str = datetime.now().strftime('%Y_%m_%d')
    report_filename = f"reports/Analiz_{date_str}.md"

    # Raporu Oluştur
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({datetime.now().strftime('%d-%m-%Y %H:%M')})\n\n"
    if results:
        report += "| Hisse | Öneri | Puan | PEG | Temel Risk |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            report += f"| **{r.name}** | {r.get_emoji()} {r.advice} | {r.score} | {r.peg} | {r.risk[:25]}... |\n"
        report += "\n---\n### 🔍 Peter Lynch Analiz Detayları\n"
        for r in results:
            report += f"#### 🔹 {r.name} ({r.code})\n- **Strateji:** {r.reason}\n- **Analiz:** {r.summary}\n- **Risk:** {r.risk}\n\n---\n"
    else:
        report += "⚠️ Veri çekilemedi. Lütfen ayarları kontrol edin."

    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"✅ Analiz tamamlandı: {report_filename}")

if __name__ == "__main__":
    main()
