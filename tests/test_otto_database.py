import sqlite3
import tempfile
import unittest
from pathlib import Path

from otto_database import (
    connect_database,
    initialize_database,
    latest_product_by_url,
    latest_products,
    latest_required_product_checks,
    prioritize_search_terms,
    record_required_product_check,
    save_products,
    start_scrape_run,
    sync_required_products,
    finish_scrape_run,
    using_stale_fallback,
)
from otto_categories import classify_category, price_band
from otto_scraper import OttoProduct
from daily_scrape import load_required_product_urls


LEGACY_SCHEMA = """
CREATE TABLE produkte (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraped_date TEXT NOT NULL,
    suchbegriff TEXT NOT NULL,
    titel TEXT NOT NULL,
    marke TEXT DEFAULT '',
    preis REAL,
    old_price REAL,
    currency TEXT DEFAULT 'EUR',
    bild_url TEXT DEFAULT '',
    produkt_url TEXT NOT NULL,
    bewertung REAL,
    anzahl_bewertungen INTEGER,
    verfuegbarkeit TEXT DEFAULT '',
    sku TEXT DEFAULT '',
    gtin TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(scraped_date, produkt_url)
)
"""


class OttoDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = connect_database(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_migration_preserves_history_and_is_idempotent(self):
        self.conn.execute(LEGACY_SCHEMA)
        legacy_records = [
            (
                "2026-09-30", "teppich", "Teppich A", "Marke A", 10.0, 20.0, "EUR",
                "", "https://www.otto.de/p/teppich-a/?tracking=one", 4.0, 8,
                "lieferbar", "sku-a", "", "2026-09-30 10:00:00",
            ),
            (
                "2026-10-01", "teppich", "Teppich A neu", "Marke A", 9.0, 20.0, "EUR",
                "", "https://www.otto.de/p/teppich-a/", 4.2, 9,
                "lieferbar", "sku-a", "", "2026-10-01 10:00:00",
            ),
        ]
        self.conn.executemany(
            """
            INSERT INTO produkte (
                scraped_date, suchbegriff, titel, marke, preis, old_price, currency,
                bild_url, produkt_url, bewertung, anzahl_bewertungen, verfuegbarkeit,
                sku, gtin, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            legacy_records,
        )
        self.conn.commit()

        initialize_database(self.conn)
        initialize_database(self.conn)

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM product_observations").fetchone()[0], 2
        )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0], 2)
        product = self.conn.execute("SELECT * FROM products").fetchone()
        self.assertEqual(product["title"], "Teppich A neu")
        self.assertEqual(product["category"], "Möbel & Wohnen")
        self.assertEqual(product["category_source"], "rule")
        self.assertEqual(product["is_required"], 0)
        latest = latest_product_by_url(
            self.conn, "https://www.otto.de/p/teppich-a?campaign=share"
        )
        self.assertEqual(latest["preis"], 9.0)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM scrape_run_summaries").fetchone()[0],
            2,
        )
        backup_path = self.db_path.with_name(f"{self.db_path.name}.pre-v5.bak")
        self.assertTrue(backup_path.exists())
        backup = sqlite3.connect(backup_path)
        try:
            self.assertEqual(
                backup.execute("SELECT COUNT(*) FROM produkte").fetchone()[0], 2
            )
            self.assertEqual(
                backup.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name = 'products'"
                ).fetchone()[0],
                0,
            )
        finally:
            backup.close()

    def test_new_observation_becomes_latest_without_erasing_history(self):
        initialize_database(self.conn)
        first_run = start_scrape_run(self.conn, 1)
        product = OttoProduct(
            title="Kopfhörer",
            brand="Beispiel",
            price=49.99,
            product_url="https://www.otto.de/p/kopfhoerer/?source=search",
        )
        save_products(self.conn, first_run, "kopfhörer", [product])
        finish_scrape_run(
            self.conn,
            first_run,
            terms_completed=1,
            terms_failed=0,
            products_seen=1,
        )

        second_run = start_scrape_run(self.conn, 1)
        product.price = 39.99
        save_products(self.conn, second_run, "kopfhörer", [product])
        finish_scrape_run(
            self.conn,
            second_run,
            terms_completed=1,
            terms_failed=0,
            products_seen=1,
        )

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM product_observations").fetchone()[0], 2
        )
        self.assertEqual(latest_products(self.conn, max_price=40)[0]["preis"], 39.99)
        self.assertEqual(
            latest_product_by_url(self.conn, product.product_url)["preis"], 39.99
        )

    def test_category_classification_is_conservative_and_tracks_contribution(self):
        self.assertEqual(
            classify_category("OTTO home Teppich Salsa")[0], "Möbel & Wohnen"
        )
        self.assertEqual(
            classify_category("Beliebiges Produkt", "Küche & Haushalt")[0],
            "Haushalt & Küche",
        )
        self.assertEqual(
            classify_category("Beliebiges Produkt", "Spezialkategorie")[0],
            "Unbekannt",
        )
        self.assertEqual(
            classify_category("Kaffeemaschine groß", "Haushalt")[0],
            "Haushalt & Küche",
        )

        initialize_database(self.conn)
        run_id = start_scrape_run(self.conn, 1)
        first = OttoProduct(
            title="Teppich",
            brand="Marke A",
            price=99.0,
            product_url="https://www.otto.de/p/teppich-a/",
        )
        duplicate = OttoProduct(
            title="Teppich",
            brand="Marke A",
            price=99.0,
            product_url="https://www.otto.de/p/teppich-a/?tracking=duplicate",
        )
        save_products(self.conn, run_id, "teppich", [first, duplicate])

        metrics = self.conn.execute(
            "SELECT * FROM search_term_metrics WHERE scrape_run_id = ?",
            (run_id,),
        ).fetchone()
        self.assertEqual(metrics["products_seen"], 2)
        self.assertEqual(metrics["new_products"], 1)
        self.assertEqual(metrics["duplicate_products"], 1)
        self.assertEqual(metrics["new_categories"], 1)
        self.assertEqual(metrics["new_brands"], 1)
        self.assertEqual(metrics["new_price_bands"], 1)
        finish_scrape_run(
            self.conn,
            run_id,
            terms_completed=1,
            terms_failed=0,
            products_seen=2,
        )
        summary = self.conn.execute(
            "SELECT * FROM scrape_run_summaries WHERE scrape_run_id = ?",
            (run_id,),
        ).fetchone()
        self.assertEqual(summary["products_observed"], 1)
        self.assertEqual(summary["products_with_price"], 1)
        bands = self.conn.execute(
            """
            SELECT value, product_count FROM scrape_run_coverage
            WHERE scrape_run_id = ? AND dimension = 'price_band'
            """,
            (run_id,),
        ).fetchone()
        self.assertEqual(bands["value"], "50–<100 €")
        self.assertEqual(bands["product_count"], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM product_observations").fetchone()[0],
            1,
        )

        next_run = start_scrape_run(self.conn, 1)
        save_products(self.conn, next_run, "teppich", [first])
        repeated = self.conn.execute(
            """
            SELECT duplicate_products FROM search_term_metrics
            WHERE scrape_run_id = ? AND search_term = 'teppich'
            """,
            (next_run,),
        ).fetchone()
        self.assertEqual(repeated["duplicate_products"], 1)

    def test_price_band_boundaries_and_currency(self):
        self.assertEqual(price_band(9.99), "<10 €")
        self.assertEqual(price_band(10.0), "10–<25 €")
        self.assertEqual(price_band(25.0), "25–<50 €")
        self.assertEqual(price_band(10_000.0), "≥10.000 €")
        self.assertIsNone(price_band(100, "USD"))

    def test_search_terms_are_ordered_by_normalized_coverage_not_hit_count(self):
        initialize_database(self.conn)
        run_id = start_scrape_run(self.conn, 2)
        diverse_products = [
            OttoProduct(
                title="Wireless Kopfhörer",
                brand="Marke A",
                price=9.0,
                product_url="https://www.otto.de/p/kopfhoerer/",
            ),
            OttoProduct(
                title="Teppich Wohnzimmer",
                brand="Marke B",
                price=30.0,
                product_url="https://www.otto.de/p/teppich/",
            ),
            OttoProduct(
                title="Solar Gartenleuchte",
                brand="Marke C",
                price=60.0,
                product_url="https://www.otto.de/p/gartenleuchte/",
            ),
        ]
        repetitive_products = [
            OttoProduct(
                title=f"Jeans Modell {index}",
                brand="Marke D",
                price=15.0 + index,
                product_url=f"https://www.otto.de/p/jeans-{index}/",
            )
            for index in range(3)
        ]
        save_products(self.conn, run_id, "vielseitig", diverse_products)
        save_products(self.conn, run_id, "einseitig", repetitive_products)
        finish_scrape_run(
            self.conn,
            run_id,
            terms_completed=2,
            terms_failed=0,
            products_seen=6,
        )

        ordered = prioritize_search_terms(
            self.conn, ["einseitig", "neu", "vielseitig"]
        )

        self.assertEqual(ordered[0], "vielseitig")
        self.assertIn("neu", ordered)

    def test_stale_data_is_used_only_when_no_recent_scrape_succeeded(self):
        initialize_database(self.conn)
        old_run = start_scrape_run(self.conn, 1)
        old_product = OttoProduct(
            title="Teppich",
            brand="Marke A",
            price=80.0,
            product_url="https://www.otto.de/p/teppich-alt/",
        )
        save_products(self.conn, old_run, "teppich", [old_product])
        finish_scrape_run(
            self.conn,
            old_run,
            terms_completed=1,
            terms_failed=0,
            products_seen=1,
        )
        self.conn.execute(
            """
            UPDATE scrape_runs
            SET started_at = datetime('now', '-2 days'),
                finished_at = datetime('now', '-2 days')
            WHERE id = ?
            """,
            (old_run,),
        )
        self.conn.execute(
            "UPDATE product_observations SET observed_at = datetime('now', '-2 days')"
        )

        failed_run = start_scrape_run(self.conn, 1)
        finish_scrape_run(
            self.conn,
            failed_run,
            terms_completed=0,
            terms_failed=1,
            products_seen=0,
        )
        self.assertTrue(using_stale_fallback(self.conn))
        self.assertEqual(latest_products(self.conn)[0]["preis"], 80.0)

        fresh_run = start_scrape_run(self.conn, 1)
        fresh_product = OttoProduct(
            title="Kopfhörer",
            brand="Marke B",
            price=50.0,
            product_url="https://www.otto.de/p/kopfhoerer/",
        )
        save_products(self.conn, fresh_run, "kopfhörer", [fresh_product])
        finish_scrape_run(
            self.conn,
            fresh_run,
            terms_completed=1,
            terms_failed=0,
            products_seen=1,
        )
        self.assertFalse(using_stale_fallback(self.conn))
        self.assertEqual([row["preis"] for row in latest_products(self.conn)], [50.0])

    def test_required_products_are_checked_and_removed_entries_deactivate(self):
        initialize_database(self.conn)
        required = sync_required_products(
            self.conn, ["https://www.otto.de/p/pflichtprodukt/?tracking=1"]
        )
        self.assertEqual(len(required), 1)

        run_id = start_scrape_run(self.conn, 1)
        product = OttoProduct(
            title="Pflichtprodukt",
            brand="Beispiel",
            price=25.0,
            product_url=required[0]["canonical_url"],
            availability="InStock",
        )
        save_products(
            self.conn,
            run_id,
            "__pflichtprodukt__",
            [product],
            record_metrics=False,
        )
        status = record_required_product_check(
            self.conn, run_id, required[0]["id"], product=product
        )
        finish_scrape_run(
            self.conn,
            run_id,
            terms_completed=1,
            terms_failed=0,
            products_seen=1,
        )

        self.assertEqual(status, "found")
        self.assertEqual(
            latest_required_product_checks(self.conn)[0]["status"], "found"
        )
        self.assertEqual(
            self.conn.execute("SELECT is_required FROM products").fetchone()[0], 1
        )

        second_run = start_scrape_run(self.conn, 1)
        product.availability = "OutOfStock"
        save_products(
            self.conn,
            second_run,
            "__pflichtprodukt__",
            [product],
            record_metrics=False,
        )
        status = record_required_product_check(
            self.conn, second_run, required[0]["id"], product=product
        )
        finish_scrape_run(
            self.conn,
            second_run,
            terms_completed=1,
            terms_failed=0,
            products_seen=1,
        )
        self.assertEqual(status, "unavailable")
        self.assertEqual(
            latest_required_product_checks(self.conn)[0]["status"], "unavailable"
        )

        sync_required_products(self.conn, [])
        self.assertEqual(latest_required_product_checks(self.conn), [])
        self.assertEqual(
            self.conn.execute("SELECT is_required FROM products").fetchone()[0], 0
        )

    def test_partial_scrape_refreshes_required_products_before_search_terms(self):
        initialize_database(self.conn)
        required = sync_required_products(
            self.conn, ["https://www.otto.de/p/pflichtprodukt/"]
        )[0]
        run_id = start_scrape_run(self.conn, 3)
        required_product = OttoProduct(
            title="Pflichtprodukt",
            brand="Beispiel",
            price=25.0,
            product_url=required["canonical_url"],
            availability="InStock",
        )
        save_products(
            self.conn,
            run_id,
            "__pflichtprodukt__",
            [required_product],
            record_metrics=False,
        )
        record_required_product_check(
            self.conn, run_id, required["id"], product=required_product
        )

        finish_scrape_run(
            self.conn,
            run_id,
            terms_completed=1,
            terms_failed=1,
            products_seen=1,
        )

        self.assertEqual(
            self.conn.execute(
                "SELECT status FROM scrape_runs WHERE id = ?", (run_id,)
            ).fetchone()[0],
            "partial",
        )
        self.assertEqual(
            latest_required_product_checks(self.conn)[0]["status"], "found"
        )
        self.assertFalse(using_stale_fallback(self.conn))
        self.assertEqual(latest_products(self.conn)[0]["titel"], "Pflichtprodukt")

    def test_successful_requests_without_products_do_not_hide_stale_catalog(self):
        initialize_database(self.conn)
        old_run = start_scrape_run(self.conn, 1)
        product = OttoProduct(
            title="Älteres Produkt",
            price=20.0,
            product_url="https://www.otto.de/p/altes-produkt/",
        )
        save_products(self.conn, old_run, "produkt", [product])
        finish_scrape_run(
            self.conn,
            old_run,
            terms_completed=1,
            terms_failed=0,
            products_seen=1,
        )
        self.conn.execute(
            """
            UPDATE scrape_runs
            SET started_at = datetime('now', '-2 days'),
                finished_at = datetime('now', '-2 days')
            WHERE id = ?
            """,
            (old_run,),
        )
        self.conn.execute(
            "UPDATE product_observations SET observed_at = datetime('now', '-2 days')"
        )

        empty_run = start_scrape_run(self.conn, 1)
        finish_scrape_run(
            self.conn,
            empty_run,
            terms_completed=1,
            terms_failed=0,
            products_seen=0,
        )

        self.assertEqual(
            self.conn.execute(
                "SELECT status FROM scrape_runs WHERE id = ?", (empty_run,)
            ).fetchone()[0],
            "failed",
        )
        self.assertTrue(using_stale_fallback(self.conn))
        self.assertEqual(latest_products(self.conn)[0]["titel"], "Älteres Produkt")

    def test_unavailable_products_are_excluded_from_current_recommendations(self):
        initialize_database(self.conn)
        run_id = start_scrape_run(self.conn, 2)
        available = OttoProduct(
            title="Lieferbares Produkt",
            price=40.0,
            product_url="https://www.otto.de/p/lieferbar/",
            availability="InStock",
        )
        unavailable = OttoProduct(
            title="Ausverkauftes Produkt",
            price=50.0,
            product_url="https://www.otto.de/p/ausverkauft/",
            availability="OutOfStock",
        )
        save_products(self.conn, run_id, "produkte", [available, unavailable])
        finish_scrape_run(
            self.conn,
            run_id,
            terms_completed=1,
            terms_failed=0,
            products_seen=2,
        )

        rows = latest_products(self.conn)

        self.assertEqual([row["titel"] for row in rows], ["Lieferbares Produkt"])
        self.assertIsNone(
            latest_product_by_url(self.conn, unavailable.product_url)
        )

    def test_required_product_file_accepts_otto_urls_and_comments_only(self):
        config = self.db_path.with_name("required.txt")
        config.write_text(
            "# Comment\nhttps://www.otto.de/p/item/?tracking=abc\n\n",
            encoding="utf-8",
        )
        self.assertEqual(
            load_required_product_urls(config),
            ["https://www.otto.de/p/item/"],
        )
        config.write_text("https://example.com/not-otto", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_required_product_urls(config)


if __name__ == "__main__":
    unittest.main()
