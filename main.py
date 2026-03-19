name: Hisse Senedi Akilli Analiz Sistemi

on:
  workflow_dispatch:
    inputs:
      mode:
        description: 'Mod'
        default: 'stocks-only'
        type: choice
        options: [full, market-only, stocks-only]

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
  PYTHONPATH: ${{ github.workspace }}
  # BİST verileri için Çin odaklı filtreleri devre dışı bırakıyoruz
  DEFAULT_MARKET: 'US'
  MARKET_REGION: 'US'
  TRADING_DAY_CHECK: 'false'

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Kütüphaneleri Yükle
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt

      - name: Analizi Gerçekleştir
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          LITELLM_MODEL: "gemini/gemini-1.5-flash"
          STOCK_LIST: ${{ vars.STOCK_LIST || secrets.STOCK_LIST }}
          # yfinance'i tek kaynak olarak zorluyoruz
          REALTIME_SOURCE_PRIORITY: 'yfinance'
          YFINANCE_FORCE_ORIGINAL: 'true'
        run: |
          mkdir -p reports
          python main.py --no-market-review --force-run

      - name: Raporu Summary Kısmına Yaz
        if: always()
        run: |
          LATEST_REPORT=$(ls -t reports/*.md 2>/dev/null | head -n 1)
          if [ -f "$LATEST_REPORT" ]; then
            echo "### 📊 Dr. Ömer - Stratejik Analiz Raporu" >> $GITHUB_STEP_SUMMARY
            cat "$LATEST_REPORT" >> $GITHUB_STEP_SUMMARY
          else
            echo "### ❌ Hata: Rapor Dosyası Bulunamadı" >> $GITHUB_STEP_SUMMARY
          fi
