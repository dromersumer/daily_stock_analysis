# main.py içindeki ilgili fonksiyonu bu şekilde güncelleyin:

def fetch_stock_data(code, session):
    """Yahoo Finance API'den ham veri çekme ve temizleme"""
    # 1 haftalık veri çekiyoruz (period1=7 gün önce)
    now = int(time.time())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&period1={now-604800}&period2={now}"
    
    res = session.get(url, impersonate="chrome")
    if res.status_code != 200:
        return None
    
    data = res.json()
    result = data.get('chart', {}).get('result', [{}])[0]
    meta = result.get('meta', {})
    indicators = result.get('indicators', {}).get('quote', [{}])[0]
    
    raw_prices = indicators.get('close', [])
    
    # --- KRİTİK PANSUMAN: None (boş) değerleri temizliyoruz ---
    prices = [p for p in raw_prices if p is not None]
    
    if len(prices) < 2:
        return None # Yeterli veri yoksa pas geç
        
    current_price = prices[-1]
    prev_price = prices[-2]
    pct_chg = round(((current_price - prev_price) / prev_price) * 100, 2)
        
    return {
        'code': code,
        'stock_name': meta.get('symbol', code),
        'today': {
            'close': round(current_price, 2),
            'pct_chg': pct_chg
        },
        'realtime': {
            'pe_ratio': 'N/A', 
            'market_cap': 'N/A'
        }
    }
