# -*- coding: utf-8 -*-
import os, sys, json, time, smtplib
from datetime import datetime
from curl_cffi import requests as cur_requests
import google.generativeai as genai
from json_repair import repair_json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        prompt = f"Hisse: {data['name']} ({data['code']}). Fiyat: {data['price']}, Değişim: %{data['change']}. Peter Lynch kriterlerine göre analiz et. Türkçe yanıtla. JSON döndür: {{\"score\": 80, \"advice\": \"Al/Tut/Sat\", \"summary\": \"...\", \"reason\": \"...\", \"risk\": \"...\", \"peg\": \"...\"}}"
        response = model.generate_content(prompt)
        d = json.loads(repair_json(response.text.replace('```json', '').replace('```', '').strip()))
        return AnalysisResult(data['code'], data['name'], d.get('score', 50), d.get('advice', 'Gözlem'), d.get('summary', ''), d.get('reason', ''), d.get('risk', ''), d.get('peg', 'N/A'))
    except Exception as e:
        return AnalysisResult(data['code'], data['name'], reason=f"AI Hatası: {str(e)[:30]}")

def send_email(report_content):
    sender = "dromersumer@gmail.com"
    password = os.getenv("EMAIL_PASSWORD")
    if not password: return
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = sender, sender, f"📈 BIST Analiz Raporu - {datetime.now().strftime('%d.%m.%Y')}"
    msg.attach(MIMEText(report_content, 'plain', 'utf-8'))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password.replace(" ", ""))
            server.sendmail(sender, sender, msg.as_string())
    except: pass

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    stock_input = os.getenv("STOCK_LIST", "THYAO.IS,AKSA.IS,TUPRS.IS")
    stock_codes = [s.strip().upper() for s in stock_input.split(',') if s.strip()]
    session, results = cur_requests.Session(), []
    
    for code in stock_codes:
        data = fetch_stock_data(code, session)
        if data:
            results.append(analyze_with_google(data, api_key))
            time.sleep(10)

    # GITHUB ÖZETİ (TABLO + DETAY)
    md = f"## 📈 Dr. Ömer - Stratejik Karar Panosu\n\n"
    md += "| Hisse | Öneri | Puan | PEG |\n| :--- | :--- | :--- | :--- |\n"
    for r in results:
        md += f"| **{r.name}** | {r.get_emoji()} {r.advice} | {r.score} | {r.peg} |\n"
    
    md += "\n---\n\n### 🔍 Detaylı Analizler\n\n"
    for r in results:
        md += f"> ### 🔹 {r.name}\n> **Durum:** {r.advice} ({r.score} Puan)\n>\n> **Strateji:** {r.reason}\n>\n> **Analiz:** {r.summary}\n>\n"
    
    # EKRANA BAS
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f: f.write(md)
            
    # MAİL AT
    plain = "\n".join([f"[{r.code}] {r.name}: {r.advice} ({r.score})" for r in results])
    send_email(plain)

if __name__ == "__main__":
    main()
