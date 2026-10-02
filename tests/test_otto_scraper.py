import json
import unittest
from unittest.mock import patch

from otto_scraper import _http_session, get_product_details


class FakeResponse:
    content = (
        "<script id='product_data_json' type='application/json'>"
        + json.dumps(
            {
                "@type": "Product",
                "name": "Testprodukt",
                "brand": {"name": "Beispiel"},
                "category": ["Haushalt", "Küche"],
                "offers": [
                    {
                        "price": "24.99",
                        "priceCurrency": "EUR",
                        "availability": "https://schema.org/OutOfStock",
                    }
                ],
            }
        )
        + "</script>"
    ).encode("utf-8")

    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, url, timeout):
        self.url = url
        self.timeout = timeout
        return FakeResponse()


class OttoScraperTests(unittest.TestCase):
    def test_product_json_ld_includes_category_and_availability(self):
        session = FakeSession()
        with patch("otto_scraper._http_session", return_value=session):
            product = get_product_details("https://www.otto.de/p/testprodukt/")

        self.assertEqual(product.title, "Testprodukt")
        self.assertEqual(product.brand, "Beispiel")
        self.assertEqual(product.category, "Haushalt / Küche")
        self.assertEqual(product.availability, "OutOfStock")
        self.assertEqual(session.timeout, (5, 20))

    def test_http_session_retries_transient_get_failures(self):
        retry = _http_session().get_adapter("https://").max_retries

        self.assertEqual(retry.total, 3)
        self.assertEqual(retry.backoff_factor, 0.5)
        self.assertIn(429, retry.status_forcelist)
        self.assertIn("GET", retry.allowed_methods)


if __name__ == "__main__":
    unittest.main()
