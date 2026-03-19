# -*- coding: utf-8 -*-
import json, logging, litellm
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
from json_repair import repair_json
from src.config import get_config

logger = logging.getLogger(__name__)

# Pipeline'ın beklediği tüm yardımcı fonksiyonlar
def check_content_integrity(result: "AnalysisResult"): return True, []
def apply_placeholder_fill(result: "AnalysisResult", fields: List[str]): pass
def fill_chip_structure_if_needed(result, chip): pass
def fill_price_position_if_needed(result, trend=None, rt=None): pass

@dataclass
class AnalysisResult:
    code: str; name: str
    sentiment_score: int = 50
    trend_prediction: str = "Yatay"
    operation_advice: str = "Gözlem"
    decision_type: str = "hold"
    dashboard: Optional[Dict] = None
    # Sistem bu alanları aradığı için boş olarak tanımlıyoruz
    analysis_summary: str = ""; ma_analysis: str = ""; volume_analysis: str = ""
    short_term_outlook: str = ""; medium_term_outlook: str = ""; risk_warning: str = ""
    buy_reason: str = ""; success: bool = True; error_message: str = ""

    def get_emoji(self):
        map = {'Güçlü Al': '💚', 'Al': '🟢', 'Tut': '🟡', 'Sat': '🔴', 'Gözlem': '⚪'}
        return map.get(self.operation_advice, '⚪')

class GeminiAnalyzer:
    SYSTEM_PROMPT = "Sen Peter Lynch tarzı bir borsa uzmanısın. Analizlerini tamamen TÜRKÇE yap. Çıktıyı JSON olarak ver."
    def __init__(self, key=None): self.model = "gemini/gemini-1.5-flash"
    def is_available(self): return True

    def analyze(self, context, news=None):
        code = context.get('code'); name = context.get('stock_name', code)
        prompt = f"Hisse: {name} ({code}) Analiz et."
        try:
            res = litellm.completion(model=self.model, messages=[{"role":"system","content":self.SYSTEM_PROMPT},{"role":"user","content":prompt}])
            data = json.loads(repair_json(res.choices[0].message.content.replace('```json', '').replace('```', '')))
            return AnalysisResult(code=code, name=name, sentiment_score=data.get('sentiment_score', 50),
                                  operation_advice=data.get('operation_advice', 'Tut'),
                                  analysis_summary=data.get('analysis_summary', ''),
                                  buy_reason=data.get('buy_reason', ''),
                                  risk_warning=data.get('risk_warning', ''),
                                  dashboard=data.get('dashboard'))
        except Exception as e:
            return AnalysisResult(code=code, name=name, success=False, error_message=str(e))
