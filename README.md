# 🔴 OTTO Aktien-Matcher

A playful Streamlit web application that matches stock/ETF prices with real products from OTTO.de (a major German e-commerce retailer). Instead of buying a stock at a certain price, why not buy real products for the same amount?

## 🎯 Features

- **Stock Search**: Search for any stock, ETF, or derivative by ticker symbol or company name
- **Price Matching**: Automatically finds the best OTTO product that costs the same or less than the selected stock price
- **Alternative Products**: Suggests what you could buy with your money (e.g., 2x, 3x, or more of cheaper products)
- **Market Data**: Displays 12-month price history and market metrics (market cap, fund size, leverage for derivatives)
- **Product Details**: Shows ratings, availability, images, and discounts for matched products
- **Shareable Links**: Generate and copy links to share your matched products and stocks

## 🏗️ Project Structure

```
├── app.py                    # Main Streamlit application
├── otto_scraper.py           # OTTO.de web scraper (BeautifulSoup)
├── daily_scrape.py           # Daily product database update script
├── yahoo_anbindung.py        # Yahoo Finance integration (stocks/ETFs)
├── streamlit_otto.py         # Streamlit UI components (deprecated)
├── otto_produkte.db          # SQLite database of OTTO products
├── randomprodukte.txt        # Sample product list
├── pyproject.toml            # Python dependencies
└── seiten/                   # Static HTML pages (if any)
```

## 🔧 Technology Stack

- **Frontend**: [Streamlit](https://streamlit.io/) 1.64+ – Interactive Python web apps without boilerplate
- **Web Scraping**: [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) – HTML parsing
- **Stock Data**: [yfinance](https://github.com/ranaroussi/yfinance) – Free Yahoo Finance data
- **Database**: SQLite – Lightweight product catalog
- **Additional**: pandas, requests, currencyconverter

## 📦 Installation

### Prerequisites
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
# Clone the repository
git clone https://github.com/lucawinterottode/YAHOO.git
cd YAHOO

# Install dependencies
uv sync
# OR: pip install -r requirements.txt (after running: pip freeze > requirements.txt)

# Run the Streamlit app
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`

## 🚀 Usage

1. **Search for a Stock**: Enter a stock ticker (e.g., "AAPL" for Apple) or company name in the search box
2. **View Matching Products**: The app displays the best OTTO product within your stock's current price
3. **Explore Alternatives**: See what multiples you could buy (2x, 3x, etc.) for the same amount
4. **Share Results**: Copy the generated link to share your stock-to-product match with others
5. **Check Details**: Click "Bei OTTO ansehen" to go directly to the product on OTTO.de

### Example
- Stock: Apple (AAPL) @ $195
- Match: OTTO finds a product costing ~€185
- Alternative: You could buy 2x products @ €90 each

## 🔄 Daily Updates

The project includes a scraper that updates the OTTO product database daily:

```bash
python daily_scrape.py
```

This script:
- Fetches products from OTTO.de based on search terms in `randomprodukte.txt`
- Parses product details (price, ratings, availability, images)
- Stores one product record plus a timestamped observation for each scrape
- Orders search terms using recent category, brand, price-band, novelty, and duplicate metrics
- Prints per-run category, price-band, brand, and data-quality coverage

## 🌐 Deployment

The app is deployed on [Streamlit Cloud](https://streamlit.io/cloud):
- **Live App**: https://otto-aktien-matcher.streamlit.app/ (You might have to wake it back up, just press the button and wait. It should take less then a minute)
- Zero-copy deployment from GitHub

To deploy your own version:
1. Push to GitHub
2. Connect your repo to Streamlit Cloud
3. Select this directory and `app.py` as the entry point

## 📊 Database Schema

The SQLite database (`otto_produkte.db`) stores the normalized product catalog in
`products`, price and availability history in `product_observations`, and scraper
execution status in `scrape_runs`. The first database initialization migrates the
existing `produkte` rows into the new tables without deleting the legacy table.
Products are keyed by a canonical product URL; individual observations retain
their scrape time and search term. Recognized OTTO categories take precedence;
conservative title rules are the fallback, and unclassified products remain
marked `Unbekannt`.
Before a schema upgrade, a file-backed database gets a versioned
`otto_produkte.db.pre-vN.bak` backup; the legacy table remains available for
rollback until explicitly removed.

Product matching accepts observations from successful or legacy runs in the last
24 hours. If there was no successful run in that window, it falls back to the latest
successful run and shows a notice in the app. Comparisons currently use EUR
products only; Yahoo stock prices are converted to EUR before matching.

The configured price bands use inclusive lower and exclusive upper bounds:
`<10`, `10–<25`, `25–<50`, `50–<100`, `100–<250`, `250–<500`,
`500–<1,000`, `1,000–<2,500`, `2,500–<5,000`, `5,000–<10,000`, and `≥10,000 EUR`.
Run coverage and per-search-term contributions are retained in
`scrape_run_coverage`, `scrape_run_summaries`, and `search_term_metrics`.

`pflichtprodukte.txt` is intentionally empty by default. Add one OTTO product
URL per line to have the daily scraper refresh it directly and report its latest
availability result in the app.

## 🎨 Features in Detail

### Stock Information
- Live price and 12-month chart
- Market capitalization (stocks) or Assets Under Management (ETFs)
- Derivative support: Shows leverage and "GIG" (Gehebelt ist Geil) easter egg 🎵

### Product Matching Algorithm
1. Find the most expensive current EUR OTTO product ≤ stock price (best main match)
2. Select up to 3 alternatives at ≤ half the stock price, preferring new categories,
   brands, and price bands while avoiding strongly similar titles
3. Calculate how many multiples of each product you can afford
4. Skip products with strongly similar titles

### Custom Formatting
- German number format (€199,99 instead of €199.99)
- Compact financial notation (e.g., "1,2 Mrd. EUR" for billions)
- Star ratings with half-stars (★★★½)

## ⚠️ Legal & Disclaimer

- **OTTO.de Terms**: This project respects OTTO.de's `robots.txt`. Scraping is done responsibly with rate limiting.
- **Derivatives Warning**: The "GIG" easter egg is a joke – derivatives and leveraged products are high-risk financial instruments.
- **No Financial Advice**: This is a fun educational tool, not financial advice.

## 👤 Author

**Luca Winter** – [GitHub](https://github.com/lucawinterottode)
**Maxim Helmer** – [GitHub](https://github.com/maximhelmerotto)
**Jonas Schneider** – [GitHub](https://github.com/jonasschneider-otto)
---

**Enjoy matching stocks to shopping carts!** 🛒📈
