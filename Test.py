from pathlib import Path

from otto_database import connect_database, initialize_database, latest_products

conn = connect_database(Path(__file__).resolve().with_name("otto_produkte.db"))
initialize_database(conn)
products = latest_products(conn)
if products:
    cheapest = min(products, key=lambda product: product["preis"])
    most_expensive = max(products, key=lambda product: product["preis"])
    print("Teuerstes:   ", tuple(most_expensive[key] for key in ("titel", "preis", "suchbegriff")))
    print("Guenstigstes:", tuple(cheapest[key] for key in ("titel", "preis", "suchbegriff")))
else:
    print("Keine aktuellen EUR-Produkte mit gültigem Preis gefunden.")
conn.close()