def get_ai_comments(orders, techs):
    comments = {}
    client = None
    
    if USE_AI and google_genai is not None:
        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                client = google_genai.Client(api_key=api_key)
        except Exception as e:
            print(f"[GEMINI INIT DEBUG] İstemci başlatılamadı: {e}")

    for o in orders:
        code = o['code']
        t = techs.get(code, {})
        
        if client and t:
            try:
                price = t.get('price', 0)
                regime = "Yükseliş Trendi" if t.get('regime') == "TREND" else "Zayıf/Düşüş Eğilimi"
                mom = t.get('mom_60', 0) * 100 
                
                prompt = (
                    f"Sen usta bir finansal algoritmik analistsin. '{code}' sembollü varlık için şu anki "
                    f"teknik verilere bak: Fiyat: {price}, Genel Durum: {regime}, 60 Günlük Momentum: %{mom:.1f}. "
                    f"Buna dayanarak en fazla 10-12 kelimelik, çok net, direkt ve Türkçe bir durum değerlendirmesi yaz. "
                    f"Sadece yorumu ver, başka bir şey yazma."
                )
                
                # Modeli en stabil versiyon olan 1.5-flash ile değiştirdik
                res = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
                yorum = res.text.strip().replace('\n', ' ')
                comments[code] = f"🤖 {yorum}"
                
            except Exception as e:
                # GITHUB ACTIONS LOGLARI İÇİN HATA AYIKLAMA (DEBUG)
                print(f"[GEMINI API DEBUG] {code} Hata Detayı: {str(e)}")
                comments[code] = "🤖 API Yanıt Vermedi."
        else:
            comments[code] = f"⚙️ Teknik: {t.get('regime', 'N/A')}"
            
    return comments
