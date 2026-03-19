# -*- coding: utf-8 -*-
import os, sys, json, time, logging, uuid, argparse
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

# --- 2. VERİ ÇEKME MOTORU (YAHOO BYPASS) ---
def fetch_stock_data(code, session):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=5d"
        res = session.get(url, impersonate="chrome")
        if res.status_code != 200: return None
        data = res.json()
        result = data['chart']['result'][0]
        prices = [p for p in result['indicators']['quote'][0]['close'] if p is not None]
        if len(prices) < 2: return None
        return {
            'code': code,
            'name': result['meta'].get('symbol', code),
            'price': round(prices[-1], 2),
            'change': round(((prices[-1] - prices[-2]) / prices[-2]) * 100, 2)
        }
    except: return None

# --- 3. AI ANALİZÖRÜ ---
def analyze_stock(data, api_key):
    prompt = f"Hisse: {data['name']}\nFiyat: {data['price']}\nDeğişim: %{data['change']}\nPeter Lynch tarzı analiz et."
    try:
        res = litellm.completion(
            model="gemini/gemini-1.5-flash",
            api_key=api_key,
            messages=[
                {"role": "system", "content": "Sen Peter Lynch'sin. Türkçe yanıtla. SADECE JSON ver: {\"score\":80,\"advice\":\"Al\",\"summary\":\"...\",\"reason\":\"...\",\"risk\":\"...\",\"peg\":\"0.5\"}"},
                {"role": "user", "content": prompt}
            ]
        )
        raw = res.choices[0].message.content.replace('```json', '').replace('```', '').strip()
        d = json.loads(repair_json(raw))
        return AnalysisResult(data['code'], data['name'], d.get('score'), d.get('advice'), d.get('summary'), d.get('reason'), d.get('risk'), d.get('peg'))
    except Exception as e:
        return AnalysisResult(data['code'], data['name'], reason=f"AI Hatası: {str(e)[:50]}")

# --- 4. ANA AKIŞ ---
def main():
    os.makedirs("reports", exist_ok=True)
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "ASELS.IS,ASTOR.IS")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    
    session = cur_requests.Session()
    results = []
    
    print(f"🚀 Analiz Başlıyor: {stock_codes}")
    for code in stock_codes:
        data = fetch_stock_data(code, session)
        if data:
            res = analyze_stock(data, api_key)
            if res: results.append(res)
        time.sleep(2)

    # RAPOR YAZMA
    now = datetime.now().strftime('%d-%m-%Y %H:%M')
    report = f"## 📈 Dr. Ömer - Stratejik Karar Panosu ({now})\n\n"
    if results:
        report += "| Hisse | Öneri | Puan | Lynch PEG | Risk |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            report += f"| **{r.name}** | {r.get_emoji()} {r.advice} | {r.score} | {r.peg} | {r.risk[:30]}... |\n"
        report += "\n### 🔍 Detaylar\n"
        for r in results:
            report += f"#### 🔹 {r.name}\n- **Analiz:** {r.summary}\n- **Neden:** {r.reason}\n\n"
    else:
        report += "⚠️ Veri çekilemedi. API anahtarını veya hisse kodlarını kontrol edin."

    with open("reports/rapor.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("✅ Rapor Hazır.")

if __name__ == "__main__":
    main()
