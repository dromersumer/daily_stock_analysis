# -*- coding: utf-8 -*-
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
import litellm
from json_repair import repair_json
from src.config import get_config

logger = logging.getLogger(__name__)

# --- Sistem Fonksiyonları (Ameliyatın devamı için şart) ---
def check_content_integrity(result: "AnalysisResult") -> Tuple[bool, List[str]]:
    missing = []
    if result.sentiment_score is None: missing.append("sentiment_score")
    if not result.operation_advice: missing.append("operation_advice")
    return len(missing) == 0, missing

def apply_placeholder_fill(result: "AnalysisResult", missing_fields: List[str]) -> None:
    for field in missing_fields:
        if field == "sentiment_score": result.sentiment_score = 50
        elif field == "operation_advice": result.operation_advice = "Gözlem"

def fill_chip_structure_if_needed(result: "AnalysisResult", chip_data: Any) -> None: pass
def fill_price_position_if_needed(result: "AnalysisResult", trend_result: Any = None, realtime_quote: Any = None) -> None: pass

@dataclass
class AnalysisResult:
    code: str
    name: str
    sentiment_score: int = 50
    trend_prediction: str = "Yatay"
    operation_advice: str = "Gözlem"
    decision_type: str = "hold"
    confidence_level: str = "Orta"
    dashboard: Optional[Dict] = None
    # Sistem bu asagidaki alanlarin varligini sart kosuyor (Hata buradaydi):
    analysis_summary: str = ""
    ma_analysis: str = ""
    volume_analysis: str = ""
    short_term_outlook: str = ""
    medium_term_outlook: str = ""
    technical_analysis: str = ""
    fundamental_analysis: str = ""
    pattern_analysis: str = ""
    sector_position: str = ""
    company_highlights: str = ""
    news_summary: str = ""
    market_sentiment: str = ""
    hot_topics: str = ""
    key_points: str = ""
    risk_warning: str = ""
    buy_reason: str = ""
    market_snapshot: Optional[Dict] = None
    raw_response: Optional[str] = None
    search_performed: bool = False
    success: bool = True
    error_message: Optional[str] = None
    model_used: Optional[str] = None

    def get_emoji(self) -> str:
        emojiler = {'Güçlü Al': '💚', 'Al': '🟢', 'Tut': '🟡', 'Sat': '🔴', 'Güçlü Sat': '❌', 'Gözlem': '⚪'}
        return emojiler.get(self.operation_advice, '⚪')

class GeminiAnalyzer:
    SYSTEM_PROMPT = """Sen Peter Lynch tarzı bir borsa uzmanısın. Analizlerini tamamen TÜRKÇE yap. 
Yanıtını SADECE şu JSON formatında ver:
{
  "stock_name": "...", "sentiment_score": 0-100, "operation_advice": "...",
  "dashboard": { "lynch_metrics": { "peg_ratio": "...", "potential": "..." } },
  "analysis_summary": "...", "risk_warning": "...", "buy_reason": "..."
}"""

    def __init__(self, api_key=None):
        config = get_config()
        # Model adini LiteLLM'in en güncel kabul ettigi formata cektik
        self.model = "gemini/gemini-1.5-flash"

    def is_available(self) -> bool: return True

    def analyze(self, context, news_context=None) -> AnalysisResult:
        code = context.get('code', 'Bilinmiyor')
        name = context.get('stock_name', code)
        
        # Veri cekme hatasi varsa Gemini'ye "Veri yok" diye bildiriyoruz
        prompt = f"Hisse: {name} ({code})\nFiyat: {context.get('today', {}).get('close', 'Veri Yok')}\nHaberler: {news_context if news_context else 'Haber yok.'}"
        
        try:
            res = litellm.completion(
                model=self.model, 
                messages=[{"role":"system","content":self.SYSTEM_PROMPT},{"role":"user","content":prompt}],
                temperature=0.2
            )
            content = res.choices[0].message.content.replace('```json', '').replace('```', '').strip()
            data = json.loads(repair_json(content))
            
            return AnalysisResult(
                code=code, name=name,
                sentiment_score=int(data.get('sentiment_score', 50)),
                operation_advice=data.get('operation_advice', 'Tut'),
                analysis_summary=data.get('analysis_summary', ''),
                buy_reason=data.get('buy_reason', ''),
                risk_warning=data.get('risk_warning', ''),
                dashboard=data.get('dashboard'),
                model_used=self.model
            )
        except Exception as e:
            logger.error(f"AI Hatasi: {e}")
            return AnalysisResult(code=code, name=name, success=False, error_message=str(e))
