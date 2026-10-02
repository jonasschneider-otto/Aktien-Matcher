"""SQLite persistence for OTTO products and their historical observations."""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from urllib.parse import unquote, urlsplit, urlunsplit

from otto_categories import (
    PRICE_BAND_COUNT,
    UNKNOWN_CATEGORY,
    classify_category,
    price_band,
)
from otto_scraper import OttoProduct

SCHEMA_VERSION = 5

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scrape_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL CHECK (
            status IN ('running', 'completed', 'partial', 'failed', 'legacy')
        ),
        terms_total INTEGER NOT NULL DEFAULT 0,
        terms_completed INTEGER NOT NULL DEFAULT 0,
        terms_failed INTEGER NOT NULL DEFAULT 0,
        products_seen INTEGER NOT NULL DEFAULT 0,
        error_message TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_url TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        brand TEXT NOT NULL DEFAULT '',
        image_url TEXT NOT NULL DEFAULT '',
        sku TEXT NOT NULL DEFAULT '',
        gtin TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'Unbekannt',
        category_raw TEXT NOT NULL DEFAULT '',
        category_source TEXT NOT NULL DEFAULT 'unknown'
            CHECK (category_source IN ('otto', 'rule', 'unknown')),
        is_required INTEGER NOT NULL DEFAULT 0 CHECK (is_required IN (0, 1)),
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingest_key TEXT NOT NULL UNIQUE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        scrape_run_id INTEGER NOT NULL REFERENCES scrape_runs(id),
        observed_at TEXT NOT NULL,
        search_term TEXT NOT NULL,
        price REAL,
        old_price REAL,
        currency TEXT NOT NULL DEFAULT 'EUR',
        rating REAL,
        review_count INTEGER,
        availability TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_observations_product_latest
    ON product_observations(product_id, observed_at DESC, id DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_observations_run
    ON product_observations(scrape_run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS search_term_metrics (
        scrape_run_id INTEGER NOT NULL REFERENCES scrape_runs(id),
        search_term TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
        products_seen INTEGER NOT NULL DEFAULT 0,
        new_products INTEGER NOT NULL DEFAULT 0,
        duplicate_products INTEGER NOT NULL DEFAULT 0,
        new_categories INTEGER NOT NULL DEFAULT 0,
        new_brands INTEGER NOT NULL DEFAULT 0,
        new_price_bands INTEGER NOT NULL DEFAULT 0,
        unique_products INTEGER NOT NULL DEFAULT 0,
        distinct_categories INTEGER NOT NULL DEFAULT 0,
        distinct_brands INTEGER NOT NULL DEFAULT 0,
        distinct_price_bands INTEGER NOT NULL DEFAULT 0,
        error_message TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (scrape_run_id, search_term)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scrape_run_coverage (
        scrape_run_id INTEGER NOT NULL REFERENCES scrape_runs(id),
        dimension TEXT NOT NULL CHECK (dimension IN ('category', 'brand', 'price_band')),
        value TEXT NOT NULL,
        product_count INTEGER NOT NULL,
        PRIMARY KEY (scrape_run_id, dimension, value)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scrape_run_summaries (
        scrape_run_id INTEGER PRIMARY KEY REFERENCES scrape_runs(id),
        products_observed INTEGER NOT NULL,
        products_with_price INTEGER NOT NULL,
        unknown_categories INTEGER NOT NULL,
        unique_brands INTEGER NOT NULL,
        duplicate_results INTEGER NOT NULL,
        min_price REAL,
        median_price REAL,
        max_price REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS required_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_url TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS required_product_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scrape_run_id INTEGER NOT NULL REFERENCES scrape_runs(id),
        required_product_id INTEGER NOT NULL REFERENCES required_products(id),
        product_id INTEGER REFERENCES products(id),
        status TEXT NOT NULL CHECK (
            status IN ('found', 'unavailable', 'unknown', 'failed')
        ),
        checked_at TEXT NOT NULL,
        availability TEXT NOT NULL DEFAULT '',
        error_message TEXT NOT NULL DEFAULT '',
        UNIQUE(scrape_run_id, required_product_id)
    )
    """,
)


def normalize_product_url(url: str) -> str:
    """Remove tracking/query data while preserving the product path."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Ungültige Produkt-URL: {url!r}")
    path = parts.path.rstrip("/") + "/" if parts.path else "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def connect_database(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def initialize_database(conn: sqlite3.Connection) -> None:
    _backup_before_migration(conn)
    for statement in _SCHEMA:
        conn.execute(statement)

    versions = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    if 1 not in versions:
        with conn:
            _migrate_legacy_products(conn)
            _record_migration(conn, 1)
    if 2 not in versions:
        with conn:
            _migrate_category_columns(conn)
            _record_migration(conn, 2)
    if 3 not in versions:
        with conn:
            _migrate_run_metrics(conn)
            _record_migration(conn, 3)
    if 4 not in versions:
        with conn:
            _migrate_search_term_quality(conn)
            _record_migration(conn, 4)
    if 5 not in versions:
        with conn:
            _record_migration(conn, 5)


def _backup_before_migration(conn: sqlite3.Connection) -> None:
    database_path = conn.execute("PRAGMA database_list").fetchone()["file"]
    if not database_path:
        return
    path = Path(database_path)
    if not path.is_file() or path.stat().st_size == 0:
        return
    migrations_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    current_version = 0
    if migrations_table:
        current_version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
    if current_version >= SCHEMA_VERSION:
        return
    backup_path = path.with_name(f"{path.name}.pre-v{SCHEMA_VERSION}.bak")
    if backup_path.exists():
        return
    backup = sqlite3.connect(backup_path)
    try:
        conn.backup(backup)
    finally:
        backup.close()


def _record_migration(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, _utc_now()),
    )


def _migrate_category_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(products)").fetchall()
    }
    if "category" not in columns:
        conn.execute(
            "ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'Unbekannt'"
        )
    if "category_raw" not in columns:
        conn.execute(
            "ALTER TABLE products ADD COLUMN category_raw TEXT NOT NULL DEFAULT ''"
        )
    if "category_source" not in columns:
        conn.execute(
            """
            ALTER TABLE products
            ADD COLUMN category_source TEXT NOT NULL DEFAULT 'unknown'
            CHECK (category_source IN ('otto', 'rule', 'unknown'))
            """
        )
    conn.execute(
        "UPDATE products SET category = ? WHERE category IS NULL OR category = ''",
        (UNKNOWN_CATEGORY,),
    )
    uncategorized = conn.execute(
        "SELECT id, title FROM products WHERE category_source = 'unknown'"
    ).fetchall()
    for product in uncategorized:
        category, category_raw, category_source = classify_category(product["title"])
        if category_source != "unknown":
            conn.execute(
                """
                UPDATE products
                SET category = ?, category_raw = ?, category_source = ?
                WHERE id = ?
                """,
                (category, category_raw, category_source, product["id"]),
            )


def _migrate_run_metrics(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(search_term_metrics)").fetchall()
    }
    if "new_price_bands" not in columns:
        conn.execute(
            """
            ALTER TABLE search_term_metrics
            ADD COLUMN new_price_bands INTEGER NOT NULL DEFAULT 0
            """
        )
    legacy_runs = conn.execute(
        """
        SELECT id FROM scrape_runs
        WHERE status = 'legacy'
          AND id NOT IN (SELECT scrape_run_id FROM scrape_run_summaries)
        """
    ).fetchall()
    for run in legacy_runs:
        _record_run_coverage(conn, run["id"])


def _migrate_search_term_quality(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(search_term_metrics)").fetchall()
    }
    for column in (
        "unique_products",
        "distinct_categories",
        "distinct_brands",
        "distinct_price_bands",
    ):
        if column not in columns:
            conn.execute(
                f"ALTER TABLE search_term_metrics ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
            )


def _migrate_legacy_products(conn: sqlite3.Connection) -> None:
    legacy_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'produkte'"
    ).fetchone()
    if not legacy_table:
        return

    legacy_rows = conn.execute(
        """
        SELECT id, scraped_date, suchbegriff, titel, marke, preis, old_price, currency,
               bild_url, produkt_url, bewertung, anzahl_bewertungen, verfuegbarkeit,
               sku, gtin, created_at
        FROM produkte
        ORDER BY scraped_date, created_at, id
        """
    ).fetchall()
    if not legacy_rows:
        return

    runs: dict[str, int] = {}
    grouped_dates = conn.execute(
        """
        SELECT scraped_date, MIN(COALESCE(created_at, scraped_date)),
               MAX(COALESCE(created_at, scraped_date)), COUNT(DISTINCT suchbegriff),
               COUNT(*)
        FROM produkte
        GROUP BY scraped_date
        ORDER BY scraped_date
        """
    ).fetchall()
    for scraped_date, started_at, finished_at, terms_total, products_seen in grouped_dates:
        cursor = conn.execute(
            """
            INSERT INTO scrape_runs (
                started_at, finished_at, status, terms_total, terms_completed, products_seen
            ) VALUES (?, ?, 'legacy', ?, ?, ?)
            """,
            (started_at, finished_at, terms_total, terms_total, products_seen),
        )
        runs[scraped_date] = cursor.lastrowid

    for row in legacy_rows:
        (
            legacy_id, scraped_date, search_term, title, brand, price, old_price, currency,
            image_url, product_url, rating, review_count, availability, sku, gtin,
            created_at,
        ) = row
        observed_at = created_at or scraped_date
        canonical_url = normalize_product_url(product_url)
        category, category_raw, category_source = classify_category(title or "")
        conn.execute(
            """
            INSERT INTO products (
                canonical_url, title, brand, image_url, sku, gtin, category,
                category_raw, category_source, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_url) DO UPDATE SET
                title = excluded.title,
                brand = CASE WHEN excluded.brand <> '' THEN excluded.brand ELSE products.brand END,
                image_url = CASE WHEN excluded.image_url <> '' THEN excluded.image_url
                                 ELSE products.image_url END,
                sku = CASE WHEN excluded.sku <> '' THEN excluded.sku ELSE products.sku END,
                gtin = CASE WHEN excluded.gtin <> '' THEN excluded.gtin ELSE products.gtin END,
                first_seen_at = MIN(products.first_seen_at, excluded.first_seen_at),
                last_seen_at = MAX(products.last_seen_at, excluded.last_seen_at)
            """,
            (
                canonical_url, title or "OTTO Produkt", brand or "", image_url or "",
                sku or "", gtin or "", category, category_raw, category_source,
                observed_at, observed_at,
            ),
        )
        product_id = conn.execute(
            "SELECT id FROM products WHERE canonical_url = ?", (canonical_url,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO product_observations (
                ingest_key, product_id, scrape_run_id, observed_at, search_term, price,
                old_price, currency, rating, review_count, availability
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"legacy:{legacy_id}", product_id, runs[scraped_date], observed_at,
                search_term or "",
                price, old_price, currency or "EUR", rating, review_count, availability or "",
            ),
        )


def start_scrape_run(conn: sqlite3.Connection, terms_total: int) -> int:
    cursor = conn.execute(
        """
        INSERT INTO scrape_runs (started_at, status, terms_total)
        VALUES (?, 'running', ?)
        """,
        (_utc_now(), terms_total),
    )
    conn.commit()
    return cursor.lastrowid


def finish_scrape_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    terms_completed: int,
    terms_failed: int,
    products_seen: int,
    error_message: str = "",
) -> None:
    run = conn.execute(
        "SELECT terms_total FROM scrape_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise ValueError(f"Unbekannter Scrape-Lauf: {run_id}")
    incomplete = terms_completed + terms_failed < run["terms_total"]
    with conn:
        _record_run_coverage(conn, run_id)
        summary = conn.execute(
            """
            SELECT products_with_price
            FROM scrape_run_summaries
            WHERE scrape_run_id = ?
            """,
            (run_id,),
        ).fetchone()
        no_products_found = (
            run["terms_total"] > 0
            and (summary is None or summary["products_with_price"] == 0)
        )
        if no_products_found:
            status = "failed"
        elif terms_failed or incomplete:
            status = "partial" if terms_completed or products_seen else "failed"
        else:
            status = "completed"
        conn.execute(
            """
            UPDATE scrape_runs
            SET finished_at = ?, status = ?, terms_completed = ?, terms_failed = ?,
                products_seen = ?, error_message = ?
            WHERE id = ?
            """,
            (
                _utc_now(), status, terms_completed, terms_failed, products_seen,
                error_message, run_id,
            ),
        )


def save_products(
    conn: sqlite3.Connection,
    run_id: int,
    search_term: str,
    products: list[OttoProduct],
    *,
    record_metrics: bool = True,
) -> int:
    with conn:
        return _save_products(
            conn, run_id, search_term, products, record_metrics=record_metrics
        )


def _save_products(
    conn: sqlite3.Connection,
    run_id: int,
    search_term: str,
    products: list[OttoProduct],
    *,
    record_metrics: bool = True,
) -> int:
    observed_at = _utc_now()
    known_urls = {
        row["canonical_url"]
        for row in conn.execute("SELECT canonical_url FROM products").fetchall()
    }
    known_categories = {
        row["category"]
        for row in conn.execute("SELECT DISTINCT category FROM products").fetchall()
        if row["category"] and row["category"] != UNKNOWN_CATEGORY
    }
    known_brands = {
        row["brand"].strip().casefold()
        for row in conn.execute("SELECT DISTINCT brand FROM products").fetchall()
        if row["brand"] and row["brand"].strip()
    }
    known_price_bands = {
        band
        for row in conn.execute(
            """
            WITH ranked AS (
                SELECT o.price, o.currency,
                       ROW_NUMBER() OVER (
                           PARTITION BY o.product_id
                           ORDER BY o.observed_at DESC, o.id DESC
                       ) AS row_num
                FROM product_observations o
            )
            SELECT price, currency FROM ranked WHERE row_num = 1
            """
        ).fetchall()
        if (band := price_band(row["price"], row["currency"])) is not None
    }
    seen_urls: set[str] = set()
    new_products = 0
    duplicate_products = 0
    new_categories: set[str] = set()
    new_brands: set[str] = set()
    new_price_bands: set[str] = set()
    distinct_categories: set[str] = set()
    distinct_brands: set[str] = set()
    distinct_price_bands: set[str] = set()
    for product in products:
        canonical_url = normalize_product_url(product.product_url)
        if canonical_url in seen_urls:
            duplicate_products += 1
            continue
        seen_urls.add(canonical_url)
        if canonical_url in known_urls:
            duplicate_products += 1
        else:
            new_products += 1
            known_urls.add(canonical_url)
        category, category_raw, category_source = classify_category(
            product.title, product.category
        )
        if category != UNKNOWN_CATEGORY and category not in known_categories:
            new_categories.add(category)
            known_categories.add(category)
        if category != UNKNOWN_CATEGORY:
            distinct_categories.add(category)
        brand_key = product.brand.strip().casefold()
        if brand_key and brand_key not in known_brands:
            new_brands.add(brand_key)
            known_brands.add(brand_key)
        if brand_key:
            distinct_brands.add(brand_key)
        band = price_band(product.price, product.currency or "EUR")
        if band and band not in known_price_bands:
            new_price_bands.add(band)
            known_price_bands.add(band)
        if band:
            distinct_price_bands.add(band)
        conn.execute(
            """
            INSERT INTO products (
                canonical_url, title, brand, image_url, sku, gtin, category,
                category_raw, category_source, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_url) DO UPDATE SET
                title = excluded.title,
                brand = CASE WHEN excluded.brand <> '' THEN excluded.brand ELSE products.brand END,
                image_url = CASE WHEN excluded.image_url <> '' THEN excluded.image_url
                                 ELSE products.image_url END,
                sku = CASE WHEN excluded.sku <> '' THEN excluded.sku ELSE products.sku END,
                gtin = CASE WHEN excluded.gtin <> '' THEN excluded.gtin ELSE products.gtin END,
                category = CASE WHEN excluded.category <> 'Unbekannt'
                                THEN excluded.category ELSE products.category END,
                category_raw = CASE WHEN excluded.category_raw <> ''
                                    THEN excluded.category_raw ELSE products.category_raw END,
                category_source = CASE WHEN excluded.category_source <> 'unknown'
                                       THEN excluded.category_source
                                       ELSE products.category_source END,
                last_seen_at = excluded.last_seen_at
            """,
            (
                canonical_url, product.title or "OTTO Produkt", product.brand or "",
                product.image_url or "", product.sku or "", product.gtin or "",
                category, category_raw, category_source, observed_at, observed_at,
            ),
        )
        product_id = conn.execute(
            "SELECT id FROM products WHERE canonical_url = ?", (canonical_url,)
        ).fetchone()["id"]
        conn.execute(
            """
            UPDATE products
            SET is_required = 1
            WHERE id = ? AND canonical_url IN (
                SELECT canonical_url FROM required_products WHERE active = 1
            )
            """,
            (product_id,),
        )
        conn.execute(
            """
            INSERT INTO product_observations (
                ingest_key, product_id, scrape_run_id, observed_at, search_term, price,
                old_price, currency, rating, review_count, availability
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ingest_key) DO UPDATE SET
                observed_at = excluded.observed_at,
                price = excluded.price,
                old_price = excluded.old_price,
                currency = excluded.currency,
                rating = excluded.rating,
                review_count = excluded.review_count,
                availability = excluded.availability
            """,
            (
                f"run:{run_id}:product:{product_id}:term:{search_term}",
                product_id, run_id, observed_at, search_term, product.price,
                product.old_price, product.currency or "EUR", product.rating,
                product.review_count, product.availability or "",
            ),
        )
    if record_metrics:
        conn.execute(
            """
            INSERT INTO search_term_metrics (
                scrape_run_id, search_term, status, products_seen, new_products,
                duplicate_products, new_categories, new_brands, new_price_bands,
                unique_products, distinct_categories, distinct_brands, distinct_price_bands
            ) VALUES (?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scrape_run_id, search_term) DO UPDATE SET
                status = excluded.status,
                products_seen = excluded.products_seen,
                new_products = excluded.new_products,
                duplicate_products = excluded.duplicate_products,
                new_categories = excluded.new_categories,
                new_brands = excluded.new_brands,
                new_price_bands = excluded.new_price_bands,
                unique_products = excluded.unique_products,
                distinct_categories = excluded.distinct_categories,
                distinct_brands = excluded.distinct_brands,
                distinct_price_bands = excluded.distinct_price_bands,
                error_message = ''
            """,
            (
                run_id, search_term, len(products), new_products, duplicate_products,
                len(new_categories), len(new_brands), len(new_price_bands),
                len(seen_urls), len(distinct_categories), len(distinct_brands),
                len(distinct_price_bands),
            ),
        )
    return len(products)


def _record_run_coverage(conn: sqlite3.Connection, run_id: int) -> None:
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT p.category, p.brand, o.price, o.currency,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.id ORDER BY o.observed_at DESC, o.id DESC
                   ) AS row_num
            FROM product_observations o
            JOIN products p ON p.id = o.product_id
            WHERE o.scrape_run_id = ?
        )
        SELECT category, brand, price, currency
        FROM ranked
        WHERE row_num = 1
        """,
        (run_id,),
    ).fetchall()
    coverage: dict[str, Counter[str]] = {
        "category": Counter(),
        "brand": Counter(),
        "price_band": Counter(),
    }
    brand_names: dict[str, str] = {}
    prices: list[float] = []
    products_with_price = 0
    unknown_categories = 0
    for row in rows:
        category = row["category"] or UNKNOWN_CATEGORY
        coverage["category"][category] += 1
        if category == UNKNOWN_CATEGORY:
            unknown_categories += 1
        brand = (row["brand"] or "").strip()
        if brand:
            normalized_brand = brand.casefold()
            brand_names.setdefault(normalized_brand, brand)
            coverage["brand"][normalized_brand] += 1
        band = price_band(row["price"], row["currency"])
        if band:
            coverage["price_band"][band] += 1
            products_with_price += 1
            prices.append(row["price"])

    conn.execute("DELETE FROM scrape_run_coverage WHERE scrape_run_id = ?", (run_id,))
    coverage_rows = [
        (run_id, dimension, brand_names.get(value, value), count)
        for dimension, counts in coverage.items()
        for value, count in counts.items()
    ]
    conn.executemany(
        """
        INSERT INTO scrape_run_coverage (scrape_run_id, dimension, value, product_count)
        VALUES (?, ?, ?, ?)
        """,
        coverage_rows,
    )
    duplicate_results = conn.execute(
        """
        SELECT COALESCE(SUM(duplicate_products), 0)
        FROM search_term_metrics
        WHERE scrape_run_id = ?
        """,
        (run_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO scrape_run_summaries (
            scrape_run_id, products_observed, products_with_price, unknown_categories,
            unique_brands, duplicate_results, min_price, median_price, max_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scrape_run_id) DO UPDATE SET
            products_observed = excluded.products_observed,
            products_with_price = excluded.products_with_price,
            unknown_categories = excluded.unknown_categories,
            unique_brands = excluded.unique_brands,
            duplicate_results = excluded.duplicate_results,
            min_price = excluded.min_price,
            median_price = excluded.median_price,
            max_price = excluded.max_price
        """,
        (
            run_id, len(rows), products_with_price, unknown_categories,
            len(brand_names), duplicate_results, min(prices) if prices else None,
            median(prices) if prices else None, max(prices) if prices else None,
        ),
    )


def record_search_term_failure(
    conn: sqlite3.Connection,
    run_id: int,
    search_term: str,
    error_message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO search_term_metrics (scrape_run_id, search_term, status, error_message)
        VALUES (?, ?, 'failed', ?)
        ON CONFLICT(scrape_run_id, search_term) DO UPDATE SET
            status = 'failed', error_message = excluded.error_message
        """,
        (run_id, search_term, error_message[:500]),
    )
    conn.commit()


def sync_required_products(
    conn: sqlite3.Connection,
    product_urls: list[str],
) -> list[sqlite3.Row]:
    normalized_urls = list(dict.fromkeys(normalize_product_url(url) for url in product_urls))
    now = _utc_now()
    with conn:
        conn.execute("UPDATE required_products SET active = 0")
        for url in normalized_urls:
            parts = urlsplit(url)
            label = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1]) or url
            conn.execute(
                """
                INSERT INTO required_products (canonical_url, label, active, created_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET active = 1, label = excluded.label
                """,
                (url, label, now),
            )
        conn.execute(
            """
            UPDATE products
            SET is_required = CASE WHEN canonical_url IN (
                SELECT canonical_url FROM required_products WHERE active = 1
            ) THEN 1 ELSE 0 END
            """
        )
    return conn.execute(
        """
        SELECT id, canonical_url, label
        FROM required_products
        WHERE active = 1
        ORDER BY canonical_url
        """
    ).fetchall()


def record_required_product_check(
    conn: sqlite3.Connection,
    run_id: int,
    required_product_id: int,
    *,
    product: OttoProduct | None = None,
    error_message: str = "",
) -> str:
    availability = (product.availability or "").strip() if product else ""
    normalized_availability = availability.casefold().replace("_", "").replace("-", "")
    if error_message:
        status = "failed"
    elif any(
        marker in normalized_availability
        for marker in ("outofstock", "nicht lieferbar", "nicht verfügbar", "ausverkauft")
    ):
        status = "unavailable"
    elif any(
        marker in normalized_availability
        for marker in ("instock", "limitedavailability", "lieferbar", "verfügbar")
    ):
        status = "found"
    else:
        status = "unknown"

    product_id = None
    if product:
        canonical_url = normalize_product_url(product.product_url)
        existing = conn.execute(
            "SELECT id FROM products WHERE canonical_url = ?", (canonical_url,)
        ).fetchone()
        product_id = existing["id"] if existing else None
    conn.execute(
        """
        INSERT INTO required_product_checks (
            scrape_run_id, required_product_id, product_id, status, checked_at,
            availability, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scrape_run_id, required_product_id) DO UPDATE SET
            product_id = excluded.product_id,
            status = excluded.status,
            checked_at = excluded.checked_at,
            availability = excluded.availability,
            error_message = excluded.error_message
        """,
        (
            run_id, required_product_id, product_id, status, _utc_now(),
            availability, error_message[:500],
        ),
    )
    conn.commit()
    return status


def latest_required_product_checks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        WITH ranked AS (
            SELECT checks.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY required_product_id
                       ORDER BY checked_at DESC, id DESC
                   ) AS row_num
            FROM required_product_checks checks
        )
        SELECT required.canonical_url, required.label, checks.status,
               checks.checked_at, checks.availability, checks.error_message
        FROM required_products required
        LEFT JOIN ranked checks
            ON checks.required_product_id = required.id AND checks.row_num = 1
        WHERE required.active = 1
        ORDER BY required.label
        """
    ).fetchall()


def prioritize_search_terms(
    conn: sqlite3.Connection,
    search_terms: list[str],
    *,
    history_limit: int = 5,
) -> list[str]:
    if history_limit <= 0:
        raise ValueError("history_limit muss positiv sein")
    history = conn.execute(
        """
        SELECT
            metrics.search_term,
            metrics.products_seen,
            metrics.new_products,
            metrics.duplicate_products,
            metrics.unique_products,
            metrics.distinct_categories,
            metrics.distinct_brands,
            metrics.distinct_price_bands
        FROM search_term_metrics metrics
        JOIN scrape_runs runs ON runs.id = metrics.scrape_run_id
        WHERE metrics.status = 'completed'
          AND runs.status IN ('completed', 'partial')
        ORDER BY runs.finished_at DESC, runs.id DESC
        """
    ).fetchall()
    term_history: dict[str, list[sqlite3.Row]] = {}
    for row in history:
        observations = term_history.setdefault(row["search_term"], [])
        if len(observations) < history_limit:
            observations.append(row)

    scores: dict[str, float] = {}
    for term, observations in term_history.items():
        weighted_score = 0.0
        total_weight = 0.0
        for age, row in enumerate(observations):
            products_seen = max(row["products_seen"], 1)
            unique_products = max(row["unique_products"], 1)
            category_coverage = row["distinct_categories"] / unique_products
            brand_coverage = row["distinct_brands"] / unique_products
            band_coverage = row["distinct_price_bands"] / min(
                PRICE_BAND_COUNT, unique_products
            )
            novelty = row["new_products"] / products_seen
            duplicate_rate = row["duplicate_products"] / products_seen
            score = (
                3 * category_coverage
                + 3 * band_coverage
                + 2 * brand_coverage
                + novelty
                - duplicate_rate
            )
            weight = 0.75**age
            weighted_score += score * weight
            total_weight += weight
        scores[term] = weighted_score / total_weight

    indexed_terms = list(enumerate(search_terms))
    return [
        term
        for _, term in sorted(
            indexed_terms,
            key=lambda item: (scores.get(item[1], 0.0), -item[0]),
            reverse=True,
        )
    ]


def latest_products(
    conn: sqlite3.Connection,
    *,
    max_price: float | None = None,
    exclude_url: str | None = None,
    limit: int | None = None,
    freshness_hours: int = 24,
) -> list[sqlite3.Row]:
    if freshness_hours <= 0:
        raise ValueError("freshness_hours muss positiv sein")
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=freshness_hours)
    ).isoformat(timespec="seconds")
    recent_success = conn.execute(
        """
        SELECT 1 FROM scrape_runs
        WHERE status IN ('completed', 'partial', 'legacy') AND finished_at >= ?
        LIMIT 1
        """,
        (cutoff,),
    ).fetchone()
    if recent_success:
        observation_filter = """
            AND o.observed_at >= ?
            AND (
                r.status IN ('completed', 'partial', 'legacy')
                OR (
                    r.status = 'running'
                    AND EXISTS (
                        SELECT 1 FROM required_product_checks checks
                        WHERE checks.scrape_run_id = r.id
                    )
                )
            )
        """
        observation_params: list[object] = [cutoff]
    else:
        fallback_run = conn.execute(
            """
            SELECT id
            FROM scrape_runs
            WHERE status IN ('completed', 'partial', 'legacy')
               OR (
                    status = 'running'
                    AND EXISTS (
                        SELECT 1 FROM required_product_checks checks
                        WHERE checks.scrape_run_id = scrape_runs.id
                    )
               )
            ORDER BY COALESCE(finished_at, started_at) DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if fallback_run is None:
            return []
        observation_filter = "AND o.scrape_run_id = ?"
        observation_params = [fallback_run["id"]]

    query = """
        WITH ranked AS (
            SELECT
                o.search_term AS suchbegriff,
                p.title AS titel,
                p.brand AS marke,
                o.price AS preis,
                o.old_price,
                o.currency,
                p.image_url AS bild_url,
                p.category,
                p.category_source,
                p.canonical_url AS produkt_url,
                o.rating AS bewertung,
                o.review_count AS anzahl_bewertungen,
                o.availability AS verfuegbarkeit,
                p.sku,
                p.gtin,
                o.observed_at,
                ROW_NUMBER() OVER (
                    PARTITION BY p.id ORDER BY o.observed_at DESC, o.id DESC
                ) AS row_num
            FROM products p
            JOIN product_observations o ON o.product_id = p.id
            JOIN scrape_runs r ON r.id = o.scrape_run_id
            WHERE 1 = 1
    """ + observation_filter + """
        )
        SELECT * FROM ranked
        WHERE row_num = 1
          AND preis IS NOT NULL AND preis > 0
          AND currency = 'EUR'
          AND LOWER(verfuegbarkeit) NOT LIKE '%outofstock%'
          AND LOWER(verfuegbarkeit) NOT LIKE '%nicht lieferbar%'
          AND LOWER(verfuegbarkeit) NOT LIKE '%nicht verfügbar%'
          AND LOWER(verfuegbarkeit) NOT LIKE '%ausverkauft%'
          AND (? IS NULL OR preis <= ?)
          AND (? IS NULL OR produkt_url <> ?)
        ORDER BY preis DESC
    """
    params = observation_params + [max_price, max_price, exclude_url, exclude_url]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return conn.execute(query, params).fetchall()


def using_stale_fallback(
    conn: sqlite3.Connection,
    *,
    freshness_hours: int = 24,
) -> bool:
    if freshness_hours <= 0:
        raise ValueError("freshness_hours muss positiv sein")
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=freshness_hours)
    ).isoformat(timespec="seconds")
    has_recent_success = conn.execute(
        """
        SELECT 1 FROM scrape_runs
        WHERE status IN ('completed', 'partial', 'legacy') AND finished_at >= ?
        LIMIT 1
        """,
        (cutoff,),
    ).fetchone()
    if has_recent_success:
        return False
    if conn.execute(
        """
        SELECT 1 FROM scrape_runs
        WHERE status IN ('completed', 'partial', 'legacy')
        LIMIT 1
        """
    ).fetchone():
        return True
    return conn.execute(
        """
        SELECT 1 FROM scrape_runs
        WHERE status = 'running'
          AND EXISTS (
              SELECT 1 FROM required_product_checks checks
              WHERE checks.scrape_run_id = scrape_runs.id
          )
        LIMIT 1
        """
    ).fetchone() is not None


def latest_product_by_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    canonical_url = normalize_product_url(url)
    return next(
        (
            product
            for product in latest_products(conn)
            if product["produkt_url"] == canonical_url
        ),
        None,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
