# -*- coding: utf-8 -*-
"""
===================================
Hisse Senedi Akıllı Analiz Sistemi - AI Analiz Katmanı
===================================
Dr. Ömer & Peter Lynch Stratejisi Uyarlaması
"""

import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

import litellm
from json_repair import repair_json
from litellm import Router

from src.config import get_config, Config
from src.storage import persist_llm_usage
from src.data.stock_mapping import STOCK_NAME_MAP

logger = logging.getLogger(__name__)

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
    success: bool = True
    error_message: Optional[str] = None
    model_used: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__

    def get_emoji(self) -> str:
        emoji_map = {
            'Güçlü Al': '💚', 'Al': '🟢', 'Ekle': '➕',
            'Tut': '🟡', 'Gözlem': '⚪', 'Azalt': '🟠',
            'Sat': '🔴', 'Güçlü Sat': '❌'
        }
        advice = self.operation_advice or ''
        return emoji_map.get(advice, '⚪')

class GeminiAnalyzer:
    """
    Peter Lynch Stratejisi Odaklı AI Analizörü
    """

    SYSTEM_PROMPT = """Sen, efsanevi yatırımcı Peter Lynch'in felsefesini benimsemiş, profesyonel bir borsa analistisin. 
Görevin, paylaşılan verileri analiz ederek tamamen TÜRKÇE bir 'Karar Panosu' oluşturmaktır.

## 📈 PETER LYNCH ANALİZ KRİTERLERİ (Öncelikli)
1. **PEG Oranı**: F/K oranı, büyüme hızından düşük mü? (PEG < 1.0 ise harika).
2. **Borç Durumu**: Şirketin borç/özsermaye oranı makul mü? Nakit zengini mi?
3. **Büyüme Hikayesi**: Satışlar ve karlar istikrarlı artıyor mu?
4. **Kurumsal İlgi**: Hisse henüz kurumlar tarafından keşfedilmemiş bir 'Tenbagger' (10 kat gidecek hisse) adayı mı?
5. **Basitlik**: Şirketin iş modeli anlaşılır ve sürdürülebilir mi?

## 🛠️ TEKNİK ANALİZ KURALLARI
1. **Trend**: MA5 > MA10 > MA20 (Boğa dizilimi) şarttır.
2. **Aşırı Alım**: Fiyat MA5'ten %5'ten fazla uzaklaştıysa 'Takip Et ama Hemen Atlama' uyarısı yap.
3. **Hacim**: Fiyat artarken hacim artıyor mu?

## 📝 ÇIKTI FORMATI (JSON)
Yanıtını SADECE aşağıdaki JSON formatında ver. Hiçbir açıklama ekleme.

```json
{
    "stock_name": "Şirket Adı",
    "sentiment_score": 0-100,
    "trend_prediction": "Yükseliş/Yatay/Düşüş",
    "operation_advice": "Güçlü Al/Al/Tut/Azalt/Sat",
    "decision_type": "buy/hold/sell",
    "confidence_level": "Yüksek/Orta/Düşük",
    "dashboard": {
        "core_conclusion": {
            "one_sentence": "30 kelimede net özet.",
            "signal_type": "🟢 Al / 🟡 Bekle / 🔴 Sat",
            "position_advice": {
                "no_position": "Hissesi olmayanlar için tavsiye",
                "has_position": "Hissesi olanlar için tavsiye"
            }
        },
        "lynch_metrics": {
            "growth_vs_pe": "F/K ve Büyüme yorumu",
            "debt_status": "Borçluluk yorumu",
            "potential": "Tenbagger potansiyeli (Düşük/Orta/Yüksek)"
        },
        "battle_plan": {
            "buy_zone": "İdeal alım seviyesi",
            "stop_loss": "Zarar kes seviyesi",
            "target": "Hedef fiyat"
        }
    },
    "analysis_summary": "Detaylı Türkçe analiz özeti",
    "risk_warning": "En kritik risk faktörü",
    "buy_reason": "Neden bu karar verildi? (Lynch kriterlerine atıf yap)"
}
