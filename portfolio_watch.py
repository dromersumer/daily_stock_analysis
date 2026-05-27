def main():
    portfolio = get_portfolio()
    if not portfolio: sys.exit(1)
        
    tickers = list(portfolio.keys())
    raw = yf.download(tickers, period="1mo", auto_adjust=True, progress=False)
    
    # Çoklu veya tekli yapı kontrolü
    if len(tickers) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw = pd.concat({tickers[0]: raw}, axis=1).swaplevel(axis=1)

    # 1. Aşama: Fiyatları ve Toplam Değeri Güvenli Hesapla
    total_value = 0
    data_map = {}
    
    for s in tickers:
        try:
            # MultiIndex veya düz yapı için esnek erişim
            level = 1 if isinstance(raw.columns, pd.MultiIndex) else 0
            close = raw.xs(s, axis=1, level=level)["Close"].dropna().iloc[-1]
            val = close * portfolio[s]
            data_map[s] = {"price": close, "val": val}
            total_value += val
        except Exception as e:
            log.warning(f"{s} için fiyat alınamadı, değer 0 kabul edildi.")
            data_map[s] = {"price": 0, "val": 0}

    # 2. Aşama: Raporu oluştur
    md = "# 🏦 Portföy Raporu\n\n| Hisse | Lot | Fiyat | Değer (USD) | Ağırlık % |\n| :--- | ---: | ---: | ---: | ---: |\n"
    
    if total_value == 0:
        md += "⚠️ Toplam portföy değeri hesaplanamadı (fiyat verisi yok).\n"
    
    for s in tickers:
        p = data_map[s]["price"]
        v = data_map[s]["val"]
        # Eğer total_value 0 ise ağırlığı 0 göster
        weight = (v / total_value * 100) if total_value > 0 else 0
        md += f"| {s} | {portfolio[s]:.2f} | ${p:.2f} | ${v:,.2f} | %{weight:.1f} |\n"
        
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.getenv("GITHUB_STEP_SUMMARY"), "w", encoding="utf-8") as f: f.write(md)
    print(md)
