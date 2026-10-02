import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daily_scrape import main
from otto_scraper import OttoProduct


class DailyScrapeTests(unittest.TestCase):
    def test_cli_records_search_metrics_and_required_product_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terms_file = root / "terms.txt"
            required_file = root / "required.txt"
            db_file = root / "catalog.db"
            terms_file.write_text('"Kopfhörer"', encoding="utf-8")
            required_file.write_text(
                "https://www.otto.de/p/pflichtprodukt/", encoding="utf-8"
            )
            search_product = OttoProduct(
                title="Kopfhörer",
                brand="Marke A",
                price=70.0,
                product_url="https://www.otto.de/p/kopfhoerer/",
                availability="InStock",
            )
            required_product = OttoProduct(
                title="Pflichtprodukt",
                brand="Marke B",
                price=20.0,
                product_url="https://www.otto.de/p/pflichtprodukt/",
                availability="OutOfStock",
            )

            with (
                patch("daily_scrape.search_otto", return_value=[search_product]),
                patch("daily_scrape.get_product_details", return_value=required_product),
            ):
                result = main(
                    [
                        "--terms-file", str(terms_file),
                        "--required-file", str(required_file),
                        "--db", str(db_file),
                        "--delay", "0",
                    ]
                )

            self.assertEqual(result, 0)
            conn = sqlite3.connect(db_file)
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 2
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT status FROM required_product_checks"
                    ).fetchone()[0],
                    "unavailable",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT status FROM scrape_runs WHERE status <> 'legacy'"
                    ).fetchone()[0],
                    "completed",
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM search_term_metrics
                        WHERE status = 'completed' AND search_term = 'Kopfhörer'
                        """
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
