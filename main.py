# -*- coding: utf-8 -*-
import os, sys, json, time
from datetime import datetime
from curl_cffi import requests as cur_requests
import google.generativeai as genai
from json_repair import repair_json

class AnalysisResult:
    def __init__(self, code, name, score=50, advice="Gözlem", summary="", reason="", risk="", peg="N/A"):
        self.code, self.name, self.score, self.advice = code, name, score, advice
        self.summary, self.reason, self.risk, self.peg = summary, reason, risk, peg
    def get_emoji(self):
        return {'Al': '🟢', 'Güçlü Al': '💚', 'Tut': '🟡', 'Sat': '🔴', 'Gözlem': '⚪'}.get(self.advice, '⚪')

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

def analyze_with_google(data, api_key):
    try:
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        selected_model = next((m for m in available_models if "1.5-flash" in m), available_models[0] if available_models else "models/gemini-1.5-flash")
        
        model = genai.GenerativeModel(selected_model)
        prompt = f"""Sen Peter Lynch tarzı uzmansın. Hisse: {data['name']} ({data['code']}). 
        Fiyat: {data['price']}, Değişim: %{data['change']}. 
        Lynch kriterlerine göre (PEG, büyüme, borç) analiz et. Türkçe yanıtla. 
        SADECE JSON döndür:
        {{"score": 80, "advice": "Al/Tut/Sat", "summary": "...", "reason": "...", "risk": "...", "peg": "..."}}"""
        
        response = model.generate_content(prompt)
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        d = json.loads(repair_json(raw_text))
        
        return AnalysisResult(
            data['code'], data['name'], d.get('score', 50), d.get('advice', 'Gözlem'),
            d.get('summary', ''), d.get('reason', ''), d.get('risk', ''), d.get('peg', 'N/A')
        )
    except Exception as e:
        return AnalysisResult(data['code'], data['name'], reason=f"AI Hatası: {str(e)[:30]}")

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "")
    portfolio_type = os.getenv("PORTFOLIO_TYPE", "BIST")
    
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    session = cur_requests.Session()
    results = []
    
    print(f"🚀 Analiz Başlıyor...")
    for i, code in enumerate(stock_codes):
        data = fetch_stock_data(code, session)
        if data:
            print(f"🧠 {code} analiz ediliyor...")
            res = analyze_with_google(data, api_key)
            results.append(res)
        time.sleep(12) # Kota dostu bekleme

    # RAPOR OLUŞTURMA
    report = f"## 📈 Dr. Ömer - {portfolio_type} Stratejik Karar Panosu\n\n"
    report += f"**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
    
    if results:
        report += "| Hisse | Öneri | Puan | PEG | Temel Risk |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            report += f"| **{r.name}** | {r.get_emoji()} {r.advice} | {r.score} | {r.peg} | {r.risk[:25]}... |\n"
        
        report += "\n---\n### 🔍 Detaylı Peter Lynch Analizleri\n"
        for r in results:
            report += f"#### 🔹 {r.name} ({r.code})\n- **Lynch Stratejisi:** {r.reason}\n- **Analiz:** {r.summary}\n- **Kritik Risk:** {r.risk}\n\n---\n"
    
    # GITHUB EKRANINA YAZDIRMA (Sihirli Kısım)
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(report)

if __name__ == "__main__":
    main()
