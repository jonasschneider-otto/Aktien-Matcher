import ast
import base64
import random
import sqlite3
import streamlit as st
from yahoo_anbindung import get_data
from streamlit_searchbox import st_searchbox
import html as _html
import yfinance as yf
import re
from otto_scraper import OttoProduct
from urllib.parse import urlencode
from st_copy import copy_button


con = sqlite3.connect("otto_produkte.db")
con.row_factory = sqlite3.Row

with open('randomprodukte.txt', 'r', encoding='utf-8') as datei:
    text = datei.read()
    randomprodukte = re.findall(r'"([^"]+)"', text)

def search_stocks(searchterm):
    if not searchterm or len(searchterm.strip()) < 2:
        return []
    try:
        result = yf.Search(searchterm, max_results=10).quotes
    except Exception:
        return [] # still schweigen, sonst Dropdown kaputt

    suggestions = []
    for q in result or []:
        symbol = q.get("symbol")
        if not symbol:
            continue
        name = q.get("longname") or q.get("shortname") or ""
        suggestions.append((f"{symbol} - {name}", symbol))
    return suggestions

def get_erstes_bild(bild_daten):
    if isinstance(bild_daten, str) and bild_daten.strip().startswith("["):
        try:
            bild_daten = ast.literal_eval(bild_daten)
        except (ValueError, SyntaxError):
            return None

    if isinstance(bild_daten, list):
        return bild_daten[0] if bild_daten else None

    return bild_daten or None

def kompakt_formatieren(betrag, währung):
    dezimalstellen = 2
    if betrag is None:
        return f"– {währung}"

    einheiten = [
        (1e12, "Bio."),
        (1e9, "Mrd."),
        (1e6, "Mio."),
        (1e3, "Tsd."),
    ]

    vorzeichen = "-" if betrag < 0 else ""
    rest = abs(betrag)

    for schwelle, suffix in einheiten:
        if rest >= schwelle:
            wert = rest / schwelle
            zahl = f"{wert:.{dezimalstellen}f}".replace(".", ",")
            return f"{vorzeichen}{zahl} {suffix} {währung}"

    zahl = f"{rest:,.{dezimalstellen}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{vorzeichen}{zahl} {währung}"


def stars(rating: float | None) -> str:
    if rating is None:
        return "–"
    full = int(rating)
    half = "½" if rating - full >= 0.5 else ""
    return "★" * full + half + f" ({rating})"


def eur(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def img_html(image_url: str) -> str:
    if image_url:
        return f'<div class="otto-img"><img src="{image_url}" alt="" loading="lazy"/></div>'
    return '<div class="otto-img otto-noimg">🛒<span>Kein Bild verfügbar</span></div>'

import re

def kurzname(produktname: str, hersteller: str) -> str:
    text = produktname

    if hersteller:
        # Hersteller entfernen, egal ob GmbH / GMBH / gmbh + flexible Leerzeichen
        pattern = r'\s+'.join(re.escape(w) for w in hersteller.split())
        text = re.sub(pattern, ' ', text, flags=re.IGNORECASE)

    # Sonderzeichen / Trennzeichen neutralisieren
    text = re.sub(r'[\(\)\[\]\"\'„“”/\\,;:\.\-–—_…!?\*+|=]', ' ', text)

    woerter = []
    woerter.append(hersteller)
    for w in text.split():
        if re.search(r'\d', w):  # keine Wörter mit Zahlen
            continue
        if len(w) < 2:  # kein -, S, M, etc.
            continue
        if not woerter.__contains__(w):
            woerter.append(w)
        if len(woerter) == 3:
            break
    return ' '.join(woerter)


OTTO_RED = "#D52B1E"


def produktkarte(p: OttoProduct) -> None:
    """Rendert eine OTTO-Produktkarte inkl. Link-Button."""
    offer = "&nbsp;"
    if p.old_price and p.discount_pct:
        offer = f'<span class="otto-badge">-{p.discount_pct} %</span><span class="otto-old">UVP {eur(p.old_price)}</span>'
    reviews = f" · {p.review_count} Bewertungen" if p.review_count else ""
    st.markdown(
        f"""
            <div class="otto-card">
              {img_html(p.image_url)}
              <div class="otto-brand">{_html.escape(p.brand) or "&nbsp;"}</div>
              <div class="otto-title" style="color:black">{_html.escape(p.title)}</div>
              <div class="otto-offer">{offer}</div>
              <div class="otto-price">{p.display_price}</div>
              <div class="otto-meta">⭐ {stars(p.rating)}{reviews}</div>
              <div class="otto-meta">📦 {_html.escape(p.availability) or "Verfügbarkeit siehe otto.de"}</div>
            </div>
            """,
        unsafe_allow_html=True,
    )
    st.link_button("Bei OTTO ansehen ↗", p.product_url, use_container_width=True)

#Design Part
oben_links, oben_rechts = st.columns([5, 1])
with oben_links:
    st.write("")
with oben_rechts:
    with open("otto.png", "rb") as datei:
        logo_daten = base64.b64encode(datei.read()).decode()
    st.markdown(
        '<a href="https://otto-aktien-matcher.streamlit.app/" target="_self">'
        f'<img src="data:image/png;base64,{logo_daten}" width="200"></a>',
        unsafe_allow_html=True,
    )
    

st.title("Otto Aktien-Matcher")

# Das interaktive Suchfeld einbinden
firmenname = st_searchbox(
    search_stocks,
    placeholder="Aktie suchen (z.B. Apple / AAPL)",
    key="stock_search"
)
# Gucken ob die Seite über einen geteilten Link geöffnet wurde
link_ticker = None
if "ticker" in st.query_params:
    link_ticker = st.query_params["ticker"]

link_produkte = []
for key in ["p0", "p1", "p2", "p3"]:
    if key in st.query_params:
        link_produkte.append(st.query_params[key])

st.set_page_config(page_title="OTTO Aktien-Matcher", page_icon="🔴", layout="centered")


auswahl = firmenname
if not auswahl:
    auswahl = link_ticker

if auswahl:
    übergabe = get_data(auswahl)
        # Gucken ob wir im Link-Modus sind
    link_modus = False
    if not firmenname:
        if link_ticker != None:
            if len(link_produkte) > 0:
                link_modus = True

    übergabe = get_data(auswahl)
    aktien_wert = übergabe.preis
    if link_modus:
        haupt_row = con.execute(
            "SELECT suchbegriff, titel, marke, preis, old_price, currency, bild_url, produkt_url, "
            "bewertung, anzahl_bewertungen, verfuegbarkeit, sku, gtin "
            "FROM produkte WHERE produkt_url = ? ",
            (link_produkte[0],),
        ).fetchone()
    else:
        haupt_row = con.execute(
            "SELECT suchbegriff, titel, marke, preis, old_price, currency, bild_url, produkt_url, "
            "bewertung, anzahl_bewertungen, verfuegbarkeit, sku, gtin "
            "FROM produkte WHERE preis IS NOT NULL AND preis > 0 AND preis <= ? "
            "AND scraped_date = (SELECT MAX(scraped_date) FROM produkte) "
            "ORDER BY preis DESC LIMIT 1",
            (aktien_wert,),
        ).fetchone()
    if haupt_row is None:
        st.error("Keine Produkte unter dem Aktienpreis in der Datenbank gefunden.")
        st.stop()

    def _map(row):
        return OttoProduct(
            title=row["titel"], brand=row["marke"] or "", price=row["preis"],
            old_price=row["old_price"], currency=row["currency"] or "EUR",
            image_url=row["bild_url"] or "", product_url=row["produkt_url"],
            rating=row["bewertung"], review_count=row["anzahl_bewertungen"],
            availability=row["verfuegbarkeit"] or "", sku=row["sku"] or "",
            gtin=row["gtin"] or "",
        )

    haupt = _map(haupt_row)
    rest = round(aktien_wert - haupt.price, 2)

    st.write(
        f"### Du kannst dir anstelle der Aktie auch 1x {kurzname(haupt.title, haupt.brand)} kaufen. "
        f"Und du hättest sogar noch {eur(rest)} über!"
    )
    if link_modus:
        alternativen = []
        rest_urls = link_produkte[1:]
        if len(rest_urls) > 3:
            rest_urls = rest_urls[0:3]
        for u in rest_urls:
            zeile = con.execute(
                "SELECT suchbegriff, titel, marke, preis, old_price, currency, bild_url, produkt_url, "
                "bewertung, anzahl_bewertungen, verfuegbarkeit, sku, gtin "
                "FROM produkte WHERE produkt_url = ? ",
                (u,),
            ).fetchone()
            if zeile != None:
                preis = zeile["preis"]
                anzahl = 2
                if preis != None:
                    if preis > 0:
                        anzahl = int(aktien_wert // preis)
                        if anzahl < 2:
                            anzahl = 2
                alternativen.append((_map(zeile), anzahl))
    else:
    # Alternativen mit Vielfachen (mind. 2x leistbar), ohne das Hauptprodukt
     alt_rows = con.execute(
        "SELECT suchbegriff, titel, marke, preis, old_price, currency, bild_url, produkt_url, "
        "bewertung, anzahl_bewertungen, verfuegbarkeit, sku, gtin "
        "FROM produkte WHERE preis IS NOT NULL AND preis > 0 AND preis <= ? "
        "AND produkt_url != ? "
        "AND scraped_date = (SELECT MAX(scraped_date) FROM produkte) "
        "ORDER BY preis DESC LIMIT 30",
        (aktien_wert / 2, haupt.product_url),
     ).fetchall()
     alternativen = []
     gesehen = {haupt_row["suchbegriff"]}
     for row in alt_rows:
        if row["suchbegriff"] not in gesehen:
            alternativen.append((_map(row), max(2, int(aktien_wert // row["preis"]))))
            gesehen.add(row["suchbegriff"])
        if len(alternativen) == 3:
            break

    mitte_links, mitte_rechts = st.columns([1, 1])

    with mitte_links:
        st.success(f"Ticker gefunden: {übergabe.ticker}")
        quote = übergabe.suche.quotes[0]
        unternehmen = quote.get("longname") or quote.get("shortname") or übergabe.ticker
        st.write(f"Unternehmen: {unternehmen}")
        if übergabe.ist_aktie:
            st.metric("letzter Preis", f"{übergabe.preis:.2f} {übergabe.währung}")
        st.write("**Kursverlauf der letzten 12 Monate:**")
        st.line_chart(übergabe.historie)
        if übergabe.ist_aktie:
            st.metric("Marktkapitalisierung", kompakt_formatieren(übergabe.marktkapitalisierung, übergabe.währung))
        else:
            st.metric("AUM", kompakt_formatieren(übergabe.fondgröße, übergabe.währung))
        if übergabe.ist_derivat:
            st.metric("Derivat Preis", f"{übergabe.derivat_preis:.2f} {übergabe.währung}")
            st.markdown(f"<p style='font-size: 150%;'>GIG - Gehebelt ist Geil</p>", unsafe_allow_html=True)
            
            st.markdown(f"<p style='font-size: 150%;'>Hebel: {übergabe.hebel:.2f}</p>", unsafe_allow_html=True)
            
            st.audio("g-i-g.mp3", format= "audio/mp3", autoplay= True)

    with mitte_rechts:

        OTTO_RED = "#D52B1E"
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

        produktkarte(haupt)
       


    if alternativen:
        alt_texte = [f"**{n}x {kurzname(p.title, p.brand)}**" for p, n in alternativen]
        if len(alt_texte) > 1:
            st.write(
                "### Alternativ auch z.B.: "
                + ", ".join(alt_texte[:-1])
                + f" oder {alt_texte[-1]}."
            )
        else:
            st.write(f"### Alternativ auch z.B.: {alt_texte[0]}.")
        cols = st.columns(len(alternativen))
        for col, (p, n) in zip(cols, alternativen):
            with col:
                st.write(f"**{n}x {kurzname(p.title, p.brand)}** ({eur(p.price)} / Stück)")
                produktkarte(p)
    _params = {"ticker": auswahl, "p0": haupt.product_url}
    for _i, (_p, _n) in enumerate(alternativen[:3], start=1):
        _params[f"p{_i}"] = _p.product_url
    share_link = "https://otto-aktien-matcher.streamlit.app/?" + urlencode(_params)
    copy_button(share_link, tooltip="Ergebnis-Link kopieren", copied_label="Kopiert! ✅", icon="st")
    st.code(share_link)       
