# -*- coding: utf-8 -*-
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import litellm
from json_repair import repair_json
from src.config import get_config

logger = logging.getLogger(__name__)

# --- Sistem Tarafından Beklenen Yardımcı Fonksiyonlar ---

def check_content_integrity(result: "AnalysisResult") -> Tuple[bool, List[str]]:
    missing: List[str] = []
    if result.sentiment_score is None: missing.append("sentiment_score")
    if not result.operation_advice: missing.append("operation_advice")
    return len(missing) == 0, missing

def apply_placeholder_fill(result: "AnalysisResult", missing_fields: List[str]) -> None:
    for field in missing_fields:
        if field == "sentiment_score": result.sentiment_score = 50
        elif field == "operation_advice": result.operation_advice = "Gözlem"

def fill_chip_structure_if_needed(result: "AnalysisResult", chip_data: Any) -> None:
    # Pipeline bu fonksiyonu arıyor, varlığını garanti ediyoruz.
    pass

def fill_price_position_if_needed(result: "AnalysisResult", trend_result: Any = None, realtime_quote: Any = None) -> None:
    # Pipeline bu fonksiyonu arıyor, varlığını garanti ediyoruz.
    pass

@dataclass
class AnalysisResult:
    code: str
    name: str
    sentiment_score: int
    trend_prediction: str
    operation_advice: str
    decision_type: str = "hold"
    confidence_level: str = "Orta"
    dashboard: Optional[Dict[str, Any]] = None
    analysis_summary: str = ""
    risk_warning: str = ""
    buy_reason: str = ""
    market_snapshot: Optional[Dict[str, Any]] = None
    raw_response: Optional[str] = None
    search_performed: bool = False
    success: bool = True
    error_message: Optional[str] = None
    model_used: Optional[str] = None

    def get_emoji(self) -> str:
        emoji_map = {'Güçlü Al': '💚', 'Al': '🟢', 'Tut': '🟡', 'Sat': '🔴', 'Güçlü Sat': '❌', 'Gözlem': '⚪'}
        return emoji_map.get(self.operation_advice, '⚪')

class GeminiAnalyzer:
    # Dr. Ömer için Peter Lynch Stratejisi
    SYSTEM_PROMPT = """Sen Peter Lynch tarzı bir borsa uzmanısın. Analizlerini tamamen TÜRKÇE yap.
Kriterlerin: PEG Oranı (F/K / Büyüme), Borç/Özsermaye dengesi, Tenbagger potansiyeli ve MA5>MA10>MA20 trendidir.

Yanıtını SADECE şu JSON formatında ver, başka metin ekleme:
{
  "stock_name": "Şirket Adı",
  "sentiment_score": 0-100,
  "trend_prediction": "Yükseliş/Düşüş/Yatay",
  "operation_advice": "Güçlü Al/Al/Tut/Sat",
  "decision_type": "buy/hold/sell",
  "dashboard": {
    "lynch_metrics": { "peg_ratio": "Değer", "potential": "Tenbagger Potansiyeli" }
  },
  "analysis_summary": "Türkçe detaylı analiz",
  "risk_warning": "En büyük risk",
  "buy_reason": "Lynch kriterlerine göre neden bu karar verildi?"
}"""

    def __init__(self, api_key: Optional[str] = None):
        config = get_config()
        self.model = config.litellm_model or "gemini/gemini-1.5-flash"

    def is_available(self) -> bool:
        return True

    def analyze(self, context: Dict[str, Any], news_context: Optional[str] = None) -> AnalysisResult:
        code = context.get('code', 'Unknown')
        name = context.get('stock_name', code)
        
        # Basit teknik ve temel veri özeti
        prompt = f"Hisse: {name} ({code})\nFiyat: {context.get('today', {}).get('close')}\nF/K: {context.get('realtime', {}).get('pe_ratio')}\nDeğişim: %{context.get('today', {}).get('pct_chg')}\nHaberler: {news_context if news_context else 'Haber yok.'}"
        
        try:
            response = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            
            res_text = response.choices[0].message.content
            cleaned_text = res_text.replace('```json', '').replace('```', '').strip()
            data = json.loads(repair_json(cleaned_text))
            
            return AnalysisResult(
                code=code, name=name,
                sentiment_score=int(data.get('sentiment_score', 50)),
                trend_prediction=data.get('trend_prediction', 'Yatay'),
                operation_advice=data.get('operation_advice', 'Tut'),
                decision_type=data.get('decision_type', 'hold'),
                dashboard=data.get('dashboard'),
                analysis_summary=data.get('analysis_summary', ''),
                risk_warning=data.get('risk_warning', ''),
                buy_reason=data.get('buy_reason', ''),
                model_used=self.model
            )
        except Exception as e:
            logger.error(f"Analiz Hatası ({name}): {e}")
            return AnalysisResult(code=code, name=name, sentiment_score=50, trend_prediction="Hata", operation_advice="Gözlem", success=False)
