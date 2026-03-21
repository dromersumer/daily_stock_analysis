# -*- coding: utf-8 -*-
import os, sys, json, time, smtplib
from datetime import datetime
from curl_cffi import requests as cur_requests
import google.generativeai as genai
from json_repair import repair_json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class AnalysisResult:
    def __init__(self, code, name, score=50, advice="Gözlem", summary="", reason="", risk="", peg="N/A", trend="N/A"):
        self.code, self.name, self.score, self.advice = code, name, score, advice
        self.summary, self.reason, self.risk, self.peg, self.trend = summary, reason, risk, peg, trend
    def get_emoji(self):
        return {'Al': '🟢', 'Güçlü Al': '💚', 'Tut': '🟡', 'Sat': '🔴', 'Gözlem': '⚪', 'BUY': '💚', 'WATCH': '🟡', 'AVOID': '🔴'}.get(self.advice, '⚪')

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
        
        # SİZİN 8 ADIMLIK PROFESYONEL PROMPT'UNUZ BURAYA ENTEGRE EDİLDİ
        prompt = f"""
        You are a professional equity analyst combining: Peter Lynch philosophy, Inflation-adjusted analysis (TMS 29), and Technical trend analysis.
        Target Stock: {data['name']} ({data['code']}). Provided Price: {data['price']}, Change: %{data['change']}.
        
        STRICT WORKFLOW:
        - STEP 1: Classify (Fast Grower, Stalwart, Cyclical, Turnaround, Asset Play). Explain WHY.
        - STEP 2: Business Understanding (Simple, scalable, growth story).
        - STEP 3: Inflation Adjustment (Detect TMS 29; if NO, adjust with CPI).
        - STEP 4: Real Fundamentals (Real growth > 10%, FX revenue bonus).
        - STEP 5: Lynch Valuation (Real PEG calculation, PEG < 1.5).
        - STEP 6: Technical Trend Analysis (EMA 21/50/200, RSI/MACD, HH/HL structure).
        - STEP 7: Confluence (Combine Fundamentals + Lynch + Trend).
        
        OUTPUT ONLY JSON (Language: Turkish for text fields):
        {{
            "score": (0-100),
            "advice": "BUY / WATCH / AVOID",
            "peg": "Real PEG value",
            "trend": "Trend status (Strong Uptrend, etc.)",
            "reason": "Lynch category, growth stats, and entry zone",
            "summary": "Business story, real vs nominal growth, bull/bear cases",
            "risk": "Inflation distortions, risk level, and balance sheet risks"
        }}
        """
        
        response = model.generate_content(prompt)
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        d = json.loads(repair_json(raw_text))
        
        return AnalysisResult(
            data['code'], data['name'], d.get('score', 50), d.get('advice', 'Gözlem'),
            d.get('summary', ''), d.get('reason', ''), d.get('risk', ''), d.get('peg', 'N/A'), d.get('trend', 'N/A')
        )
    except Exception as e:
        return AnalysisResult(data['code'], data['name'], reason=f"AI Hatası: {str(e)[:40]}")

def send_email(report_content):
    sender_email = "dromersumer@gmail.com"
    password = os.getenv("EMAIL_PASSWORD")
    if not password: return
    msg = MIMEMultipart()
    msg['From'], msg['To'] = sender_email, sender_email
    msg['Subject'] = f"📈 Profesyonel Karar Raporu (TMS 29 + Teknik) - {datetime.now().strftime('%d.%m.%Y')}"
    msg.attach(MIMEText(report_content, 'plain', 'utf-8'))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, password.replace(" ", ""))
            server.sendmail(sender_email, sender_email, msg.as_string())
    except: pass

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "")
    portfolio_type = os.getenv("PORTFOLIO_TYPE", "BIST")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    session, results = cur_requests.Session(), []
    
    for i, code in enumerate(stock_codes):
        data = fetch_stock_data(code, session)
        if data:
            results.append(analyze_with_google(data, api_key))
        time.sleep(8) # Kota dostu mola

    # GITHUB ÖZETİ (PROFESYONEL FORMAT)
    md = "<small>\n\n"
    md += f"## 📈 Dr. Ömer - {portfolio_type} Stratejik Analiz Panosu (Ultra-Pro)\n\n"
    md += f"**Tarih:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
    
    if results:
        md += "| Hisse | Öneri | Puan | PEG (Reel) | Trend |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for r in results:
            md += f"| **{r.name}** | {r.get_emoji()} {r.advice} | {r.score} | {r.peg} | {r.trend} |\n"
        
        md += "\n---\n### 🔍 Detaylı Karar Destek Analizleri\n"
        for r in results:
            md += f"#### 🔹 {r.name} ({r.code})\n"
            md += f"- **Karar:** {r.get_emoji()} **{r.advice}** ({r.score} Puan) | **PEG:** {r.peg} | **Trend:** {r.trend}\n"
            md += f"- **Stratejik Görünüm:** {r.reason}\n"
            md += f"- **Analiz Özeti:** {r.summary}\n"
            md += f"- **Risk Seviyesi & TMS 29:** {r.risk}\n\n---\n"
    else:
        md += "⚠️ Veri çekilemedi.\n"
    
    md += "\n</small>"

    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f: f.write(md)
            
    send_email(md.replace("<small>", "").replace("</small>", ""))

if __name__ == "__main__":
    main()
