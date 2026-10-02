"""Täglicher OTTO-Scrape mit Produktbeobachtungen und Abdeckungsmetriken.

Aufruf:
    python daily_scrape.py
    python daily_scrape.py --limit 5 --db otto_produkte.db
    python daily_scrape.py --required-file pflichtprodukte.txt
    python daily_scrape.py --max-terms 2 --limit 2   # zum Testen

Die GitHub Action ruft später einfach `python daily_scrape.py` einmal am Tag auf.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from otto_database import (
    connect_database,
    finish_scrape_run,
    initialize_database,
    record_required_product_check,
    record_search_term_failure,
    save_products,
    start_scrape_run,
    sync_required_products,
    normalize_product_url,
    prioritize_search_terms,
)
from otto_scraper import get_product_details, search_otto

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TERMS_FILE = BASE_DIR / "randomprodukte.txt"
DEFAULT_REQUIRED_FILE = BASE_DIR / "pflichtprodukte.txt"
DEFAULT_DB = BASE_DIR / "otto_produkte.db"
DEFAULT_LIMIT = 5


def load_search_terms(path: Path) -> list[str]:
    """Liest alle \"Suchbegriffe\" aus randomprodukte.txt (gleiche Logik wie app.py)."""
    text = path.read_text(encoding="utf-8")
    terms = [t.strip() for t in re.findall(r'"([^"]+)"', text) if t.strip()]
    # Duplikate entfernen, Reihenfolge behalten
    return list(dict.fromkeys(terms))


def load_required_product_urls(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            canonical_url = normalize_product_url(value)
            if urlsplit(canonical_url).hostname not in {"otto.de", "www.otto.de"}:
                raise ValueError(f"Pflichtprodukt muss auf otto.de liegen: {value}")
            urls.append(canonical_url)
    return list(dict.fromkeys(urls))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OTTO Daily-Scrape in SQLite-DB")
    parser.add_argument("--terms-file", type=Path, default=DEFAULT_TERMS_FILE)
    parser.add_argument("--required-file", type=Path, default=DEFAULT_REQUIRED_FILE)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="Produkte pro Suchbegriff (default: 5)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Pause in Sekunden zwischen Suchbegriffen (default: 1.0)")
    parser.add_argument("--max-terms", type=int, default=0,
                        help="Nur für Tests: max. Anzahl Suchbegriffe (0 = alle)")
    args = parser.parse_args(argv)

    if not args.terms_file.exists():
        print(f"FEHLER: Suchbegriffe-Datei nicht gefunden: {args.terms_file}", file=sys.stderr)
        return 2
    if not args.required_file.exists():
        print(f"FEHLER: Pflichtprodukt-Datei nicht gefunden: {args.required_file}", file=sys.stderr)
        return 2

    terms = load_search_terms(args.terms_file)
    try:
        required_urls = load_required_product_urls(args.required_file)
    except ValueError as e:
        print(f"FEHLER in Pflichtprodukt-Datei: {e}", file=sys.stderr)
        return 2
    if args.max_terms and args.max_terms > 0:
        terms = terms[: args.max_terms]

    conn = connect_database(args.db)
    initialize_database(conn)
    terms = prioritize_search_terms(conn, terms)
    required_products = sync_required_products(conn, required_urls)
    print(
        f"{len(terms)} Suchbegriffe aus {args.terms_file.name}, je {args.limit} Produkte "
        f"(nach Abdeckungsbeitrag sortiert), {len(required_products)} Pflichtprodukte "
        f"-> {args.db.name}"
    )
    run_id = start_scrape_run(conn, len(terms) + len(required_products))

    total_saved = 0
    terms_completed = 0
    failed: list[str] = []
    interrupted = False
    for i, required in enumerate(required_products, 1):
        try:
            product = get_product_details(required["canonical_url"])
            n = save_products(
                conn,
                run_id,
                "__pflichtprodukt__",
                [product],
                record_metrics=False,
            )
            status = record_required_product_check(
                conn, run_id, required["id"], product=product
            )
            terms_completed += 1
            total_saved += n
            print(
                f"[Pflichtprodukt {i}/{len(required_products)}] "
                f"{required['label']}: {status}"
            )
        except KeyboardInterrupt:
            print("\nAbgebrochen durch Benutzer.", file=sys.stderr)
            terms = []
            interrupted = True
            break
        except Exception as e:  # noqa: BLE001 - Pflichtproduktfehler werden pro URL protokolliert
            failed.append(required["label"])
            record_required_product_check(
                conn, run_id, required["id"], error_message=str(e)
            )
            print(
                f"[Pflichtprodukt {i}/{len(required_products)}] "
                f"{required['label']}: FEHLER {e}",
                file=sys.stderr,
            )
        if args.delay > 0 and (i < len(required_products) or terms):
            time.sleep(args.delay)

    for i, term in enumerate(terms, 1):
        try:
            products = search_otto(term, limit=args.limit)
            n = save_products(conn, run_id, term, products)
            terms_completed += 1
            contribution = conn.execute(
                """
                SELECT new_products, duplicate_products, new_categories, new_brands,
                       new_price_bands
                FROM search_term_metrics
                WHERE scrape_run_id = ? AND search_term = ?
                """,
                (run_id, term),
            ).fetchone()
            if not products:
                print(f"[{i}/{len(terms)}] '{term}': keine Treffer")
            else:
                total_saved += n
                print(
                    f"[{i}/{len(terms)}] '{term}': {n} Treffer, "
                    f"{contribution['new_products']} neu, "
                    f"{contribution['new_categories']} neue Kategorien, "
                    f"{contribution['new_brands']} neue Marken, "
                    f"{contribution['new_price_bands']} neue Preisbänder, "
                    f"{contribution['duplicate_products']} Duplikate im Ergebnis"
                )
        except KeyboardInterrupt:
            print("\nAbgebrochen durch Benutzer.", file=sys.stderr)
            interrupted = True
            break
        except Exception as e:  # noqa: BLE001 - ein Begriff darf den Day-Run nicht killen
            failed.append(term)
            record_search_term_failure(conn, run_id, term, str(e))
            print(f"[{i}/{len(terms)}] '{term}': FEHLER {e}", file=sys.stderr)
        if args.delay > 0 and i < len(terms):
            time.sleep(args.delay)
    finish_scrape_run(
        conn,
        run_id,
        terms_completed=terms_completed,
        terms_failed=len(failed),
        products_seen=total_saved,
        error_message=", ".join(failed[:10]),
    )
    summary = conn.execute(
        "SELECT * FROM scrape_run_summaries WHERE scrape_run_id = ?",
        (run_id,),
    ).fetchone()
    if summary:
        print(
            "Laufabdeckung: "
            f"{summary['products_observed']} eindeutige Produkte, "
            f"{summary['products_with_price']} mit EUR-Preis, "
            f"{summary['unknown_categories']} ohne erkannte Kategorie, "
            f"{summary['unique_brands']} Marken."
        )
    for dimension in ("category", "price_band"):
        values = conn.execute(
            """
            SELECT value, product_count FROM scrape_run_coverage
            WHERE scrape_run_id = ? AND dimension = ?
            ORDER BY value
            """,
            (run_id, dimension),
        ).fetchall()
        if values:
            print(
                f"{dimension}: "
                + ", ".join(f"{row['value']}={row['product_count']}" for row in values)
            )
    brands = conn.execute(
        """
        SELECT value, product_count FROM scrape_run_coverage
        WHERE scrape_run_id = ? AND dimension = 'brand'
        ORDER BY product_count DESC, value
        LIMIT 10
        """,
        (run_id,),
    ).fetchall()
    if brands:
        print(
            "Marken (Top 10): "
            + ", ".join(f"{row['value']}={row['product_count']}" for row in brands)
        )
    conn.close()
    print(f"Fertig: {total_saved} Produktbeobachtungen gespeichert.")
    if failed:
        print(f"{len(failed)} Einträge fehlgeschlagen: {', '.join(failed[:10])}"
              + (" ..." if len(failed) > 10 else ""), file=sys.stderr)
    return 0 if total_saved > 0 and not failed and not interrupted else 1


if __name__ == "__main__":
    sys.exit(main())
