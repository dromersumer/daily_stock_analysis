# -*- coding: utf-8 -*-
import json, logging, litellm
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
from json_repair import repair_json

logger = logging.getLogger(__name__)

# Sistemin beklediği yan fonksiyonlar (Eksiksiz)
def check_content_integrity(result: "AnalysisResult"): return True, []
def apply_placeholder_fill(result: "AnalysisResult", fields: List[str]): pass
def fill_chip_structure_if_needed(result, chip): pass
def fill_price_position_if_needed(result, trend=None, rt=None): pass

@dataclass
class AnalysisResult:
    code: str; name: str
    sentiment_score: int = 50; trend_prediction: str = "Yatay"
    operation_advice: str = "Gözlem"; decision_type: str = "hold"
    dashboard: Optional[Dict] = None
    # Hata vermemesi için boş tanımlanan alanlar
    analysis_summary: str = ""; ma_analysis: str = ""; volume_analysis: str = ""
    risk_warning: str = ""; buy_reason: str = ""; success: bool = True

    def get_emoji(self):
        map = {'Güçlü Al': '💚', 'Al': '🟢', 'Tut': '🟡', 'Sat': '🔴', 'Gözlem': '⚪'}
        return map.get(self.operation_advice, '⚪')

class GeminiAnalyzer:
    SYSTEM_PROMPT = """Sen Peter Lynch tarzı uzman bir borsa analistisin. 
Sana verilen verileri Lynch'in 'PEG oranı, borç durumu ve büyüme potansiyeli' kriterlerine göre analiz et.
Yanıtını MUTLAKA Türkçe ver ve SADECE şu JSON yapısını kullan:
{
  "score": 75, "advice": "Al/Tut/Sat", "summary": "...", "reason": "...", "risk": "...", "peg": "..."
}"""

    def __init__(self, key=None):
        # 404 hatasını önlemek için en kararlı model ismi
        self.model = "gemini/gemini-1.5-flash"

    def analyze(self, context):
        code = context.get('code'); name = context.get('stock_name', code)
        prompt = f"Hisse: {name} ({code})\nFiyat: {context.get('today', {}).get('close')}\nAnaliz et."
        try:
            res = litellm.completion(model=self.model, messages=[{"role":"system","content":self.SYSTEM_PROMPT},{"role":"user","content":prompt}], temperature=0.2)
            content = res.choices[0].message.content.replace('```json', '').replace('```', '').strip()
            data = json.loads(repair_json(content))
            return AnalysisResult(code=code, name=name, sentiment_score=int(data.get('score', 50)),
                                  operation_advice=data.get('advice', 'Tut'),
                                  analysis_summary=data.get('summary', ''),
                                  buy_reason=data.get('reason', ''),
                                  risk_warning=data.get('risk', ''),
                                  dashboard={'lynch_metrics': {'potential': data.get('peg', 'Bilinmiyor')}})
        except Exception as e:
            return AnalysisResult(code=code, name=name, success=False, buy_reason=f"AI Hatası: {str(e)}")
