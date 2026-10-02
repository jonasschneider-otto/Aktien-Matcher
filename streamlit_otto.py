"""OTTO Produktfenster in Streamlit.

Start:  streamlit run src/streamlit_otto.py
"""

import html as _html

import streamlit as st

from otto_scraper import OttoProduct, get_product_details, search_otto

OTTO_RED = "#D52B1E"

st.set_page_config(page_title="OTTO Produktfenster", page_icon="🛒", layout="wide")

st.markdown(
    f"""
    <style>
    /* Alle Zeilen haben feste Höhen -> alle Karten sind gleich groß */
    .otto-card {{
        background: #fff; border-radius: 12px; padding: 14px;
        box-shadow: 0 1px 6px rgba(0,0,0,.12);
        display: flex; flex-direction: column;
    }}
    .otto-img {{
        height: 200px; border-radius: 8px; background: #f7f7f7;
        display: flex; align-items: center; justify-content: center; overflow: hidden;
    }}
    .otto-img img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
    .otto-noimg {{ flex-direction: column; gap: 4px; color: #aaa; font-size: 2.2rem; }}
    .otto-noimg span {{ font-size: .8rem; }}
    .otto-brand {{
        color: #666; font-size: .8rem; text-transform: uppercase; height: 1.4em; margin-top: 8px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .otto-title {{
        font-weight: 700; font-size: .95rem; line-height: 1.3; height: 2.6em; overflow: hidden;
        display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    }}
    .otto-category {{ color: #777; font-size: .75rem; height: 1.2em; }}
    .otto-category {{ color: #777; font-size: .75rem; height: 1.2em; }}
    .otto-offer {{ height: 1.5em; font-size: .85rem; }}
    .otto-old {{ color: #888; text-decoration: line-through; }}
    .otto-badge {{
        display: inline-block; background: {OTTO_RED}; color: #fff;
        font-size: .75rem; font-weight: 700; border-radius: 6px; padding: 1px 8px; margin-right: 6px;
    }}
    .otto-price {{ color: {OTTO_RED}; font-weight: 800; font-size: 1.25rem; height: 1.8em; }}
    .otto-meta {{
        color: #555; font-size: .8rem; height: 1.5em;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛒 OTTO Produktfenster")
st.caption("Live-Produkte von otto.de via requests + BeautifulSoup")

with st.sidebar:
    st.header("Suche")
    modus = st.radio("Modus", ["Suche", "Produkt-URL"], horizontal=True)
    anzahl = st.slider("Anzahl Produkte", 3, 24, 9)
    suchen_btn = st.button("Laden", type="primary")

if modus == "Suche":
    query = st.text_input("Suchbegriff", value="tv")
    produkt_url = ""
else:
    produkt_url = st.text_input(
        "OTTO Produkt-URL",
        value="https://www.otto.de/p/apple-iphone-15-plus-128gb-smartphone-17-cm-67-zoll-128-gb-speicherplatz-48-mp-kamera-1786937979/",
    )
    query = ""

produkte: list[OttoProduct] = []

if suchen_btn or "produkte" not in st.session_state:
    try:
        with st.spinner("Lade OTTO-Daten …"):
            if modus == "Suche" and query.strip():
                produkte = search_otto(query.strip(), limit=anzahl)
            elif modus == "Produkt-URL" and produkt_url.strip():
                produkte = [get_product_details(produkt_url.strip())]
        st.session_state["produkte"] = produkte
    except Exception as e:  # noqa: BLE001
        st.error(f"OTTO konnte nicht geladen werden: {e}")
        produkte = st.session_state.get("produkte", [])
else:
    produkte = st.session_state.get("produkte", [])

if not produkte:
    st.info("Links in der Sidebar Suchbegriff oder Produkt-URL eingeben und **Laden** klicken.")
    st.stop()


def stars(rating: float | None) -> str:
    if rating is None:
        return "–"
    full = int(rating)
    half = "½" if rating - full >= 0.5 else ""
    return "★" * full + half + f" ({rating})"


def eur(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return ""
    symbol = "€" if currency == "EUR" else currency
    return (
        f"{value:,.2f} {symbol}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def img_html(image_url: str) -> str:
    if image_url:
        return f'<div class="otto-img"><img src="{image_url}" alt="" loading="lazy"/></div>'
    return '<div class="otto-img otto-noimg">🛒<span>Kein Bild verfügbar</span></div>'


cols = st.columns(3)
for i, p in enumerate(produkte):
    with cols[i % 3]:
        offer = "&nbsp;"
        if p.old_price and p.discount_pct:
            offer = (
                f'<span class="otto-badge">-{p.discount_pct} %</span>'
                f'<span class="otto-old">UVP {eur(p.old_price, p.currency)}</span>'
            )
        reviews = f" · {p.review_count} Bewertungen" if p.review_count else ""
        category = _html.escape(p.category) if p.category else ""
        st.markdown(
            f"""
            <div class="otto-card">
              {img_html(p.image_url)}
              <div class="otto-brand">{_html.escape(p.brand) or "&nbsp;"}</div>
              <div class="otto-title">{_html.escape(p.title)}</div>
              <div class="otto-category">{category}</div>
              <div class="otto-offer">{offer}</div>
              <div class="otto-price">{p.display_price}</div>
              <div class="otto-meta">⭐ {stars(p.rating)}{reviews}</div>
              <div class="otto-meta">📦 {_html.escape(p.availability) or "Verfügbarkeit siehe otto.de"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.link_button("Bei OTTO ansehen ↗", p.product_url, use_container_width=True)

with st.expander("🔍 Detailansicht & Rohdaten"):
    auswahl = st.selectbox("Produkt wählen", range(len(produkte)), format_func=lambda i: produkte[i].title)
    p = produkte[auswahl]
    c1, c2 = st.columns([1, 2])
    with c1:
        if p.image_url:
            st.image(p.image_url, use_container_width=True)
    with c2:
        st.subheader(p.title)
        st.metric("Preis", p.display_price)
        st.write(f"**Marke:** {p.brand or '–'} | **SKU:** {p.sku or '–'} | **GTIN:** {p.gtin or '–'}")
        if p.details.get("beschreibung"):
            st.write(p.details["beschreibung"])
        st.link_button("Zum Produkt", p.product_url)
