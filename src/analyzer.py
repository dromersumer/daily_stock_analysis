# analyzer.py içindeki GeminiAnalyzer sınıfını bu şekilde güncelleyin:
class GeminiAnalyzer:
    def __init__(self, key=None):
        # 404 hatasını önlemek için EN STABİL model ismi
        self.model = "gemini/gemini-1.5-flash" 

    def analyze(self, context):
        code = context.get('code')
        name = context.get('stock_name', code)
        # Gemini'ye giden Türkçe talimat
        prompt = f"Hisse: {name} ({code})\nFiyat: {context.get('today', {}).get('close')}\nLynch tarzı analiz et."
        
        try:
            # litellm üzerinden çağrı
            import litellm
            from json_repair import repair_json
            res = litellm.completion(
                model=self.model, 
                messages=[{"role":"system","content":"Sen Peter Lynch'sin. Türkçe yanıtla. Çıktı SADECE JSON olsun: {\"score\":80,\"advice\":\"Al\",\"summary\":\"...\",\"reason\":\"...\",\"risk\":\"...\",\"peg\":\"0.5\"}"},
                          {"role":"user","content":prompt}]
            )
            data = json.loads(repair_json(res.choices[0].message.content.replace('```json','').replace('```','')))
            # AnalysisResult nesnesini döndür (Önceki tanımlarla uyumlu)
            from src.analyzer import AnalysisResult
            return AnalysisResult(
                code=code, name=name, sentiment_score=int(data.get('score', 50)),
                operation_advice=data.get('advice', 'Tut'),
                analysis_summary=data.get('summary', ''),
                buy_reason=data.get('reason', ''),
                risk_warning=data.get('risk', ''),
                dashboard={'lynch_metrics': {'potential': data.get('peg', 'Bilinmiyor')}}
            )
        except Exception as e:
            return None
