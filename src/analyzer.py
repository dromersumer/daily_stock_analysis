# -*- coding: utf-8 -*-
import json, logging, litellm, time
from dataclasses import dataclass
from typing import Optional, Dict, Any
from json_repair import repair_json
from src.config import get_config

logger = logging.getLogger(__name__)

@dataclass
class AnalysisResult:
    code: str; name: str; sentiment_score: int; trend_prediction: str; operation_advice: str
    decision_type: str = "hold"; dashboard: Optional[Dict] = None; analysis_summary: str = ""
    risk_warning: str = ""; buy_reason: str = ""; success: bool = True; model_used: str = ""

class GeminiAnalyzer:
    SYSTEM_PROMPT = """Sen Peter Lynch tarzı bir borsa uzmanısın. Analizlerini tamamen TÜRKÇE yap.
Kriterlerin: PEG Oranı, Borç/Özsermaye, Tenbagger potansiyeli ve MA5>MA10>MA20 trendi.
Yanıtını SADECE şu JSON formatında ver:
{
  "stock_name": "...", "sentiment_score": 0-100, "operation_advice": "Güçlü Al/Al/Tut/Sat",
  "dashboard": { "lynch_metrics": { "peg_ratio": "...", "potential": "..." } },
  "analysis_summary": "...", "risk_warning": "...", "buy_reason": "..."
}"""

    def __init__(self):
        config = get_config()
        self.model = config.litellm_model or "gemini/gemini-1.5-flash"

    def analyze(self, context: Dict, news_context: str = None) -> AnalysisResult:
        code = context.get('code')
        name = context.get('stock_name', code)
        prompt = f"Hisse: {name}\nFiyat: {context.get('today', {}).get('close')}\nF/K: {context.get('realtime', {}).get('pe_ratio')}\nHaberler: {news_context}"
        
        try:
            res = litellm.completion(model=self.model, messages=[{"role":"system","content":self.SYSTEM_PROMPT},{"role":"user","content":prompt}])
            data = json.loads(repair_json(res.choices[0].message.content))
            return AnalysisResult(code=code, name=name, sentiment_score=data.get('sentiment_score', 50), 
                                  trend_prediction="Analiz Edildi", operation_advice=data.get('operation_advice', 'Tut'),
                                  dashboard=data.get('dashboard'), analysis_summary=data.get('analysis_summary'),
                                  risk_warning=data.get('risk_warning'), buy_reason=data.get('buy_reason'))
        except Exception as e:
            return AnalysisResult(code=code, name=name, sentiment_score=50, trend_prediction="Hata", operation_advice="Gözlem")

    def is_available(self): return True
