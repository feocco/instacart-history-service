from pathlib import Path

from instacart_history.importer import InstacartCsvImporter
from instacart_history.repository import HistoryRepository


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_importer_parses_current_export_variants_and_is_idempotent(tmp_path) -> None:
    data_dir = tmp_path / "exports"
    write(
        data_dir / "account-a" / "family_orders" / "INSTACART_FAMILY Order History-2026 Order Report .csv",
        "\n".join(
            [
                "",
                "Platform ,INSTACART_FAMILY",
                "Period ,2026 Order Report,",
                "Total Orders,1",
                "Grand Total ,34.29,USD",
                "Total Shipments,1",
                "Total Items Ordered,1",
                "See Sheet 2 (Purchased Items) for item titles and descriptions,",
                "",
                "",
                "Order Type,Order ID,Order Date,No. of Shipment,No. of Items,Payment Methods,Currency,Sub Total,Promotion,Coupon,Gift Card,Additional Fees,Shipping & Handling,Total Before Tax,VAT (TAX),Grand Total,Refund Total,Purchased Item Description,Invoice URL,Order URL,Shipping Address,Store Name",
                'Regular,19246577453429960,"Feb 05, 2026",1,1,Visa 1111,USD,34.29,0,0,0,0,0,34.29,0,34.29,0,items,https://invoice.example,https://order.example,"1 Loop Road",wegmans',
            ]
        ),
    )
    write(
        data_dir / "account-a" / "family_orders" / "INSTACART_FAMILY Purchased Items-2026 Order Report.csv",
        "\n".join(
            [
                "",
                "Product Order Type,Order Date,Order ID,Item Number/ASIN,Payment Methods,Product Description,Product Quantity,Store Name,Sub-Category 1,Sub-Category 2,Additional Categories,Product Price,Price Paid (Before-Tax),Currency,Invoice URL,Product URL,Shipping Address (item),Gift Card Recipient,Gift Card Status,Product Image",
                'Regular,"Feb 05, 2026",19246577453429960,24756,Visa 1111,"De Cecco Rigatoni, No. 24",1,wegmans,,,,3.49,3.49,USD,https://invoice.example,https://www.instacart.com/products/24756,"1 Loop Road",,,https://image.example/rigatoni.jpg',
            ]
        ),
    )
    write(
        data_dir / "account-b" / "individual_orders" / "INSTACART Purchased Items-2024 Order Report.csv",
        "\n".join(
            [
                "",
                "Product Order Type,Order Date,Order ID,Item Number/ASIN,Payment Methods,Product Description,Product Quantity,Store Name,Product Price,Price Paid (Before-Tax),Currency,Invoice URL,Product URL,Shipping Address (item),Product Image",
                'Delivered,"Dec 23, 2024",15716705678423176,18446687,Visa 5104,"Betty Crocker Mug Treats",1,target,3.99,3.99,USD,https://invoice.example,https://www.instacart.com/products/18446687,"2821 White Birch",https://image.example/mug.png',
            ]
        ),
    )
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    importer = InstacartCsvImporter(repo)

    first = importer.import_directory(data_dir)
    second = importer.import_directory(data_dir)

    assert first.orders_created == 1
    assert first.items_created == 2
    assert second.orders_created == 0
    assert second.orders_updated == 1
    assert second.items_created == 0
    assert second.items_updated == 2
    rigatoni = repo.find_products("rigatoni")[0]
    assert rigatoni.title == "De Cecco Rigatoni, No. 24"
    assert rigatoni.account_label == "account-a/family_orders"
    assert rigatoni.product_url == "https://www.instacart.com/products/24756"
    assert "Gift Card Status" in repo.get_order_item(rigatoni.id).raw_payload


def test_importer_handles_real_instacart_export_directory(tmp_path) -> None:
    source = Path("/Users/feocco/code/grocery-research/data/instacart")
    if not source.exists():
        return
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    result = InstacartCsvImporter(repo).import_directory(source)

    assert result.orders_created >= 300
    assert result.items_created >= 7000
    assert repo.find_products("eggs")
