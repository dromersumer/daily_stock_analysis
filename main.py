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
        # None (boş) fiyatları temizle
        prices = [p for p in result['indicators']['quote'][0]['close'] if p is not None]
        if len(prices) < 2: return None
        return {
            'code': code,
            'name': result['meta'].get('symbol', code),
            'price': round(prices[-1], 2),
            'change': round(((prices[-1] - prices[-2]) / prices[-2]) * 100, 2)
        }
    except: return None

# --- 3. GOOGLE RESMİ SDK ANALİZÖR ---
def analyze_with_google(data, api_key):
    try:
        genai.configure(api_key=api_key)
        # 404 hatasını önlemek için resmi model ismi
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""Sen Peter Lynch tarzı uzman bir borsa analistisin. 
Hisse: {data['name']} ({data['code']}) | Fiyat: {data['price']} | Değişim: %{data['change']}
Bu verileri Lynch kriterlerine (PEG, büyüme potansiyeli, borç durumu) göre analiz et. 
Türkçe yanıtla. SADECE JSON formatında şu yapıyı döndür:
{{
  "score": 80,
  "advice": "Al/Tut/Sat",
  "summary": "Kısa ve öz analiz sonucu",
  "reason": "Neden bu kararı verdiğinin Lynch kriteriyle açıklaması",
  "risk": "Hisse için en kritik risk faktörü",
  "peg": "Tahmini PEG oranı"
}}"""

        response = model.generate_content(prompt)
        # Markdown bloklarını temizle
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        d = json.loads(repair_json(raw_text))
        
        return AnalysisResult(
            data['code'], data['name'], 
            d.get('score', 50), d.get('advice', 'Gözlem'), 
            d.get('summary', ''), d.get('reason', ''), 
            d.get('risk', ''), d.get('peg', 'N/A')
        )
    except Exception as e:
        return AnalysisResult(data['code'], data['name'], reason=f"Google AI Hatası: {str(e)[:50]}")

# --- 4. ANA AKIŞ ---
def main():
    os.makedirs("reports", exist_ok=True)
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "ASELS.IS,ASTOR.IS,THYAO.IS,TUPRS.IS")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    
    session = cur_requests.Session()
    results = []
    
    print(f"🚀 Operasyon Başlıyor: {stock_codes}")
    for code in stock_codes:
        data = fetch_stock_data(code, session)
        if data:
            res = analyze_with_google(data, api_key)
            if res: results.append(res)
        time.sleep(1.5) # IP blokajı riskine karşı güvenlik molası

    # RAPOR OLUŞTURMA
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
    if results:
        report += "| Hisse | Öneri | Puan | PEG | Temel Risk |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            report += f"| **{r.name}** | {r.get_emoji()} {r.advice} | {r.score} | {r.peg} | {r.risk[:25]}... |\n"
        
        report += "\n---\n### 🔍 Peter Lynch Analiz Detayları\n"
        for r in results:
            report += f"#### 🔹 {r.name} ({r.code})\n"
            report += f"- **Strateji:** {r.reason}\n"
            report += f"- **Analiz:** {r.summary}\n"
            report += f"- **Kritik Risk:** {r.risk}\n\n---\n"
    else:
        report += "⚠️ Veri çekilemedi. API anahtarını veya hisse listesini kontrol edin."

    with open("reports/rapor.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("✅ Rapor Başarıyla Oluşturuldu.")

if __name__ == "__main__":
    main()
