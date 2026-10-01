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
- Stores data in `otto_produkte.db` SQLite database

## 🌐 Deployment

The app is deployed on [Streamlit Cloud](https://streamlit.io/cloud):
- **Live App**: https://otto-aktien-matcher.streamlit.app/ (You might have to wake it back up, just press the button and wait. It should take less then a minute)
- Zero-copy deployment from GitHub

To deploy your own version:
1. Push to GitHub
2. Connect your repo to Streamlit Cloud
3. Select this directory and `app.py` as the entry point

## 📊 Database Schema

The SQLite database (`otto_produkte.db`) contains a `produkte` table with:
- `suchbegriff` – Search query used
- `titel`, `marke` – Product title and brand
- `preis`, `old_price`, `currency` – Current and original prices
- `bild_url` – Product image
- `produkt_url` – OTTO.de product link
- `bewertung`, `anzahl_bewertungen` – Star rating and review count
- `verfuegbarkeit` – Availability status
- `sku`, `gtin` – Product identifiers
- `scraped_date` – When the data was collected

## 🎨 Features in Detail

### Stock Information
- Live price and 12-month chart
- Market capitalization (stocks) or Assets Under Management (ETFs)
- Derivative support: Shows leverage and "GIG" (Gehebelt ist Geil) easter egg 🎵

### Product Matching Algorithm
1. Find the most expensive OTTO product ≤ stock price (best main match)
2. Find 3 alternative products at ≤ half the stock price
3. Calculate how many multiples of each product you can afford
4. Filter out duplicates by search term

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
