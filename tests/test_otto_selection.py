import unittest

from otto_selection import select_diverse_alternatives


def product(title, brand, category, price, url):
    return {
        "titel": title,
        "marke": brand,
        "category": category,
        "preis": price,
        "currency": "EUR",
        "produkt_url": url,
    }


class ProductSelectionTests(unittest.TestCase):
    def test_selects_alternatives_across_categories_brands_and_price_bands(self):
        main = product(
            "Wireless Kopfhörer Noise Cancelling",
            "Marke A",
            "Elektronik & Technik",
            80,
            "https://otto.test/main",
        )
        candidates = [
            product(
                "Wireless Kopfhörer Noise Cancelling schwarz",
                "Marke A",
                "Elektronik & Technik",
                75,
                "https://otto.test/similar",
            ),
            product(
                "Handgewebter Teppich Wohnzimmer",
                "Marke B",
                "Möbel & Wohnen",
                45,
                "https://otto.test/carpet",
            ),
            product(
                "Solar Gartenleuchte Außenbereich",
                "Marke C",
                "Garten",
                15,
                "https://otto.test/lamp",
            ),
            product(
                "Teppich Läufer Flur",
                "Marke D",
                "Möbel & Wohnen",
                20,
                "https://otto.test/runner",
            ),
        ]

        selected = select_diverse_alternatives(candidates, main, limit=3)

        self.assertEqual(
            [item["produkt_url"] for item in selected],
            ["https://otto.test/carpet", "https://otto.test/lamp", "https://otto.test/runner"],
        )

    def test_returns_fewer_products_instead_of_repeating_similar_items(self):
        main = product(
            "Wireless Kopfhörer Noise Cancelling Modell 2026",
            "Marke A",
            "Elektronik & Technik",
            80,
            "https://otto.test/main",
        )
        similar = product(
            "Wireless Kopfhörer Noise Cancelling Modell 2027",
            "Marke B",
            "Elektronik & Technik",
            70,
            "https://otto.test/similar",
        )

        self.assertEqual(select_diverse_alternatives([similar], main, limit=3), [])


if __name__ == "__main__":
    unittest.main()
