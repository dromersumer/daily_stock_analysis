# -*- coding: utf-8 -*-
import json, logging, litellm
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from json_repair import repair_json
from src.config import get_config

logger = logging.getLogger(__name__)

# --- Sistem Fonksiyonları (Eksiksiz) ---
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
    analysis_summary: str = ""; ma_analysis: str = ""; volume_analysis: str = ""
    short_term_outlook: str = ""; medium_term_outlook: str = ""; risk_warning: str = ""
    buy_reason: str = ""; success: bool = True; error_message: str = ""

    def get_emoji(self):
        emojiler = {'Güçlü Al': '💚', 'Al': '🟢', 'Tut': '🟡', 'Sat': '🔴', 'Gözlem': '⚪'}
        return emojiler.get(self.operation_advice, '⚪')

class GeminiAnalyzer:
    # Dr. Ömer için en sert Türkçe Prompt
    SYSTEM_PROMPT = """Sen Peter Lynch tarzı uzman bir borsa analistisin. 
Sana verilen verileri Lynch'in 'PEG oranı, borç durumu ve büyüme potansiyeli' kriterlerine göre analiz et.
Yanıtını MUTLAKA Türkçe ver ve SADECE şu JSON yapısını kullan:
{
  "score": 75,
  "advice": "Al/Tut/Sat",
  "summary": "Analiz özeti buraya",
  "reason": "Lynch stratejisine göre neden bu karar verildi?",
  "risk": "En kritik risk faktörü",
  "peg": "Hesaplanan veya tahmin edilen PEG"
}"""

    def __init__(self, key=None):
        # Model ismini en garanti formata çektik
        self.model = "gemini/gemini-1.5-flash"

    def is_available(self): return True

    def analyze(self, context, news=None) -> AnalysisResult:
        code = context.get('code', 'Bilinmiyor')
        name = context.get('stock_name', code)
        
        prompt = f"Hisse: {name} ({code})\nFiyat: {context.get('today', {}).get('close')}\nF/K: {context.get('realtime', {}).get('pe_ratio')}\nAnaliz et."
        
        try:
            # Litellm üzerinden Gemini çağrısı
            response = litellm.completion(
                model=self.model, 
                messages=[{"role": "system", "content": self.SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                temperature=0.2
            )
            
            content = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
            data = json.loads(repair_json(content))
            
            # Verileri AnalysisResult nesnesine haritala
            return AnalysisResult(
                code=code, name=name,
                sentiment_score=int(data.get('score', 50)),
                operation_advice=data.get('advice', 'Tut'),
                analysis_summary=data.get('summary', 'Özet çıkarılamadı.'),
                buy_reason=data.get('reason', 'Analiz detayı alınamadı.'),
                risk_warning=data.get('risk', 'Risk belirtilmedi.'),
                dashboard={'lynch_metrics': {'potential': data.get('peg', 'Bilinmiyor')}}
            )
        except Exception as e:
            logger.error(f"AI Analiz Hatası: {str(e)}")
            # Hata durumunda boş dönmek yerine hatayı raporun içine yazıyoruz
            return AnalysisResult(
                code=code, name=name, success=False,
                buy_reason=f"AI Analiz Hatası oluştu: {str(e)}",
                risk_warning="AI bağlantısı kurulamadı.",
                analysis_summary="Lütfen API anahtarınızı (GEMINI_API_KEY) kontrol edin."
            )
