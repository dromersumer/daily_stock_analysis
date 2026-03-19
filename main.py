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

# --- 3. AKILLI AI ANALİZÖRÜ (404 SAVAR) ---
def analyze_with_google(data, api_key):
    genai.configure(api_key=api_key)
    # 2026 için en olası model isimleri (Sırasıyla denenecek)
    models_to_try = ['gemini-1.5-flash-latest', 'gemini-1.5-flash', 'gemini-pro', 'gemini-1.0-pro']
    
    last_error = ""
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            prompt = f"""Sen Peter Lynch tarzı uzmansın. Hisse: {data['name']} ({data['code']}). 
            Fiyat: {data['price']}, Değişim: %{data['change']}. 
            Türkçe analiz et. SADECE JSON döndür:
            {{"score": 80, "advice": "Al/Tut/Sat", "summary": "...", "reason": "...", "risk": "...", "peg": "..."}}"""
            
            response = model.generate_content(prompt)
            raw_text = response.text.replace('```json', '').replace('```', '').strip()
            d = json.loads(repair_json(raw_text))
            
            return AnalysisResult(
                data['code'], data['name'], d.get('score', 50), d.get('advice', 'Gözlem'),
                d.get('summary', ''), d.get('reason', ''), d.get('risk', ''), d.get('peg', 'N/A')
            )
        except Exception as e:
            last_error = str(e)
            continue # Hata verirse bir sonraki modeli dene
            
    return AnalysisResult(data['code'], data['name'], reason=f"AI Hatası: {last_error[:50]}")

# --- 4. ANA AKIŞ ---
def main():
    os.makedirs("reports", exist_ok=True)
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "ASELS.IS,ASTOR.IS,THYAO.IS,TUPRS.IS,YUNSA.IS")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    
    session = cur_requests.Session()
    results = []
    
    print(f"🚀 Analiz Başlıyor (Dr. Ömer Özel)...")
    for code in stock_codes:
        data = fetch_stock_data(code, session)
        if data:
            res = analyze_with_google(data, api_key)
            if res: results.append(res)
        time.sleep(1)

    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
    if results:
        report += "| Hisse | Öneri | Puan | PEG | Temel Risk |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            report += f"| **{r.name}** | {r.get_emoji()} {r.advice} | {r.score} | {r.peg} | {r.risk[:25]}... |\n"
        report += "\n---\n### 🔍 Peter Lynch Analiz Detayları\n"
        for r in results:
            report += f"#### 🔹 {r.name} ({r.code})\n- **Strateji:** {r.reason}\n- **Analiz:** {r.summary}\n- **Risk:** {r.risk}\n\n---\n"
    else:
        report += "⚠️ Veri çekilemedi. API anahtarınızı (GEMINI_API_KEY) kontrol edin."

    with open("reports/rapor.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("✅ Bitti.")

if __name__ == "__main__":
    main()
