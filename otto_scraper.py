"""OTTO.de Scraper für Streamlit-Integration.

Nutzt nur requests + BeautifulSoup (kein Selenium nötig),
da OTTO Such- und Produktseiten serverseitig rendert.

- Suche: https://www.otto.de/suche/<begriff>/ -> Produkt-Tiles (article)
- Detail: https://www.otto.de/p/.../ -> JSON-LD (script#product_data_json)
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import local
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.otto.de"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}
_THREAD_LOCAL = local()


def _http_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.headers.update(HEADERS)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _THREAD_LOCAL.session = session
    return session


@dataclass
class OttoProduct:
    """Ein Produkt im OTTO-Produktfenster."""

    title: str
    brand: str = ""
    price: float | None = None
    old_price: float | None = None
    currency: str = "EUR"
    image_url: str = ""
    product_url: str = ""
    rating: float | None = None
    review_count: int | None = None
    availability: str = ""
    sku: str = ""
    gtin: str = ""
    category: str = ""
    details: dict = field(default_factory=dict)

    @property
    def display_price(self) -> str:
        if self.price is None:
            return "Preis auf Anfrage"
        symbol = "€" if self.currency == "EUR" else self.currency
        return (
            f"{self.price:,.2f} {symbol}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

    @property
    def discount_pct(self) -> int | None:
        if self.price and self.old_price and self.old_price > self.price:
            return round((1 - self.price / self.old_price) * 100)
        return None


def _cents_to_euro(value: str | None) -> float | None:
    """'19999' (Cent) -> 199.99. Falls schon Euro-Format, direkt parsen."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value) / 100
    # Fallback: "199,99 €" -> 199.99
    m = re.search(r"([\d.]+),(\d{2})", value)
    if m:
        return float(m.group(1).replace(".", "") + "." + m.group(2))
    return None


def _parse_price_text(text: str) -> float | None:
    return _cents_to_euro(text)


def _prices_from_text(text: str) -> tuple[float | None, float | None]:
    """Preis + UVP aus Fließtext ziehen, z. B. 'ab 199,99 € UVP 379,00 €'."""
    price = old = None
    m = re.search(r"([\d.]+,\d{2})\s*€", text or "")
    if m:
        price = _cents_to_euro(m.group(1))
    m_old = re.search(r"UVP\s*([\d.]+,\d{2})", text or "")
    if m_old:
        old = _cents_to_euro(m_old.group(1))
    return price, old


def _normalize_image_url(url: str) -> str:
    """OTTO-Bild-URL auf das funktionierende $formatz$-Preset normieren.

    Die Tile-Parameter `$responsive_ft2$` + `$DIM$` liefern nur ein ca.
    11 KB großes Platzhalterbild; `?$formatz$` liefert das echte Produktfoto.
    """
    url = (url or "").replace("&amp;", "&").strip()
    if not url:
        return ""
    if "i.otto.de" in url:
        return url.split("?")[0] + "?$formatz$"
    return url


def _safe_details(stub: OttoProduct) -> OttoProduct | None:
    """Platzhalter-Produkt über die Detailseite anreichern (mit Fallback)."""
    try:
        full = get_product_details(stub.product_url)
        if not full.title or full.title == "OTTO Produkt":
            full.title = stub.title
        if not full.sku:
            full.sku = stub.sku
        if not full.category:
            full.category = stub.category
        return full
    except Exception:
        return stub if stub.title and stub.product_url else None


def search_otto(query: str, limit: int = 12) -> list[OttoProduct]:
    """Sucht auf otto.de und gibt bis zu `limit` Produkte zurück.

    Nur wenige Tiles sind serverseitig voll gerendert (Preis, Bild). Der Rest
    sind Platzhalter-Tiles (nur Titel + Link) und wird parallel über die
    Produkt-Detailseiten (JSON-LD) angereichert.
    """
    url = f"{BASE_URL}/suche/{quote_plus(query.strip())}/"
    resp = _http_session().get(url, timeout=(5, 20))
    resp.raise_for_status()
    # content (bytes) statt text: BeautifulSoup wertet dann <meta charset="utf-8">
    # selbst aus, sonst wird € falsch dekodiert und die Preis-Regex greift nicht.
    soup = BeautifulSoup(resp.content, "html.parser")

    products: list[OttoProduct] = []
    to_enrich: list[OttoProduct] = []
    seen: set[str] = set()

    for article in soup.find_all("article"):
        if len(products) + len(to_enrich) >= limit:
            break

        link = article.find("a", href=lambda h: h and "/p/" in h)
        if not link:
            continue
        href = link.get("href", "")
        full_url = urljoin(BASE_URL, href.split("?")[0])
        if full_url in seen:
            continue
        seen.add(full_url)

        pricing = article.find("ofc-pricing-item-v1")
        img = article.find("img")
        source = article.find("source", srcset=True)
        if pricing is None and img is None and source is None:
            # Platzhalter-Tile (wird per JS nachgeladen) -> später anreichern
            title = (link.get("title") or link.get_text(" ", strip=True) or "OTTO Produkt").strip()
            to_enrich.append(
                OttoProduct(
                    title=title,
                    product_url=full_url,
                    sku=article.get("data-product-id", ""),
                    category=article.get("data-category", ""),
                )
            )
            continue

        brand_el = article.find("span", class_=lambda c: c and "reptile-product-brand" in c)
        title_el = article.find("span", class_=lambda c: c and "reptile-product-title" in c)
        brand = brand_el.get_text(strip=True) if brand_el else ""
        short_title = title_el.get_text(strip=True) if title_el else ""
        title = f"{brand} {short_title}".strip() or link.get("aria-label", "OTTO Produkt")

        image_url = ""
        if img is not None and img.get("src"):
            image_url = _normalize_image_url(img.get("src"))
        if not image_url and source is not None:
            # srcset kann mehrere Kandidaten enthalten -> ersten nehmen
            image_url = _normalize_image_url(source.get("srcset", "").split()[0])

        price = _cents_to_euro(pricing.get("retail-price")) if pricing else None
        old_price = _cents_to_euro(pricing.get("suggested-retail-price")) if pricing else None
        if price is None:
            # Mal Web-Component mit Attributen, mal nur Fließtext ("ab 199,99 €")
            tprice, told = _prices_from_text(article.get_text(" ", strip=True))
            price = tprice
            if old_price is None:
                old_price = told

        rating: float | None = None
        review_count: int | None = None
        rating_el = article.find("span", class_=lambda c: c and "reptile-rating__amount" in c)
        if rating_el:
            m = re.search(r"\((\d+)\)", rating_el.get_text())
            if m:
                review_count = int(m.group(1))
        stars = article.find_all("oc-icon-v1", attrs={"type": True})
        if stars:
            full = sum(1 for s in stars if s.get("type") == "rating-filled")
            half = sum(1 for s in stars if s.get("type") == "rating-half")
            rating = full + 0.5 * half or None

        avail_el = article.find("span", attrs={"data-testid": "AvailabilityText"})
        availability = avail_el.get_text(strip=True) if avail_el else ""

        products.append(
            OttoProduct(
                title=title,
                brand=brand,
                price=price,
                old_price=old_price,
                image_url=image_url,
                product_url=full_url,
                rating=rating,
                review_count=review_count,
                availability=availability,
                sku=article.get("data-product-id", ""),
                category=article.get("data-category", ""),
            )
        )

    if to_enrich:
        # Platzhalter-Tiles parallel über Detailseiten mit echten Daten füllen
        with ThreadPoolExecutor(max_workers=5) as pool:
            for full in pool.map(_safe_details, to_enrich):
                if full is not None:
                    products.append(full)

    return products[:limit]


def get_product_details(product_url: str) -> OttoProduct:
    """Lädt eine OTTO-Produktseite (/p/...) und parst das JSON-LD."""
    if product_url.startswith("/"):
        product_url = urljoin(BASE_URL, product_url)
    resp = _http_session().get(product_url, timeout=(5, 20))
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    script = soup.find("script", id="product_data_json") or soup.find(
        "script", type="application/ld+json"
    )
    if not script:
        raise ValueError("Kein Produkt-JSON (JSON-LD) auf der Seite gefunden.")

    data = json.loads(script.string or script.get_text())
    if isinstance(data, list):
        data = next((d for d in data if d.get("@type") == "Product"), data[0])

    brand = data.get("brand", {})
    brand_name = brand.get("name") if isinstance(brand, dict) else str(brand or "")
    raw_category = data.get("category", "")
    if isinstance(raw_category, (list, tuple)):
        category = " / ".join(str(value) for value in raw_category if value)
    elif isinstance(raw_category, dict):
        category = str(raw_category.get("name", ""))
    else:
        category = str(raw_category or "")

    images = data.get("image", [])
    if isinstance(images, str):
        images = [images]
    image_url = (images[0] if images else "").replace("&amp;", "&")

    offers = data.get("offers", {}) or {}
    if isinstance(offers, list):
        offers = next((offer for offer in offers if isinstance(offer, dict)), {})
    price = float(offers.get("price")) if offers.get("price") else None
    currency = offers.get("priceCurrency", "EUR") or "EUR"
    offer_url = offers.get("url", product_url)
    availability = str(offers.get("availability", "") or "")

    agg = data.get("aggregateRating", {}) or {}
    rating = float(agg.get("ratingValue")) if agg.get("ratingValue") else None
    review_count = int(agg.get("reviewCount")) if agg.get("reviewCount") else None

    og_desc = soup.find("meta", property="og:description")
    details = {}
    if og_desc and og_desc.get("content"):
        details["beschreibung"] = og_desc["content"].strip()[:500]

    return OttoProduct(
        title=data.get("name", "OTTO Produkt"),
        brand=brand_name or "",
        price=price,
        currency=currency,
        image_url=image_url,
        product_url=offer_url or product_url,
        rating=rating,
        review_count=review_count,
        availability=availability.rsplit("/", 1)[-1],
        sku=str(data.get("sku", "")),
        gtin=str(data.get("gtin13", "")),
        category=category,
        details=details,
    )


if __name__ == "__main__":  # kleiner manueller Test
    for p in search_otto("tv", limit=3):
        print(f"- {p.title} | {p.display_price} | {p.product_url}")
