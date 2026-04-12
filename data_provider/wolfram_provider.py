import wolframalpha
import os

class WolframValuationProvider:
    def __init__(self):
        # API Anahtarını doğrudan koda yazmıyoruz (Güvenlik için)
        # Bunu daha sonra GitHub Secrets kısmına ekleyeceğiz
        self.api_key = os.getenv("WOLFRAM_ALPHA_APPID")
        if self.api_key:
            self.client = wolframalpha.Client(self.api_key)
        else:
            self.client = None

    def get_stock_valuation(self, ticker):
        """Hisse senedi için Wolfram Alpha'dan temel değerleme verilerini çeker."""
        if not self.client:
            return "Wolfram API anahtarı bulunamadı."

        # BIST hisseleri için sorgu formatını ayarlıyoruz
        query = f"BIST:{ticker} financial ratios and intrinsic value"
        
        try:
            res = self.client.query(query)
            # Wolfram'dan gelen tüm veriyi (pod'ları) birleştirip özetliyoruz
            summary = []
            for pod in res.pods:
                for subpod in pod.subpods:
                    if subpod.plaintext:
                        summary.append(f"{pod.title}: {subpod.plaintext}")
            
            return "\n".join(summary) if summary else "Veri bulunamadı."
        except Exception as e:
            return f"Wolfram sorgusu sırasında hata oluştu: {str(e)}"
