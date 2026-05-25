# API

## Health

```http
GET /health
```

Response:

```json
{"status":"ok"}
```

## Import Instacart CSV Exports

```http
POST /v1/import/instacart-csv
```

Request:

```json
{"data_dir":"/Users/feocco/code/grocery-research/data/instacart"}
```

Response:

```json
{
  "files_seen": 14,
  "orders_created": 318,
  "orders_updated": 0,
  "items_created": 7821,
  "items_updated": 0,
  "rows_skipped": 0
}
```

Counts depend on the current export folder. Re-importing the same files updates
existing rows instead of creating duplicates.

For POC imports into a remote Mac mini service, CSV file contents can be posted
without committing order data:

```http
POST /v1/import/instacart-csv-files
```

Request:

```json
{
  "files": [
    {
      "relative_path": "account/family/INSTACART_FAMILY Purchased Items-2026 Order Report.csv",
      "content": "Product Order Type,Order Date,..."
    }
  ]
}
```

## Recommend Products For Ingredients

```http
POST /v1/recommendations/ingredients
```

Request:

```json
{
  "ingredients": [
    {"food_name": "rigatoni", "quantity": 1, "unit_name": "box"}
  ]
}
```

The endpoint also accepts a top-level `consolidated` array or `by_recipe` array
from `mealie-planner`.

Response:

```json
{
  "ingredients": [
    {
      "food_name": "rigatoni",
      "quantity": 1,
      "unit_name": "box",
      "recommended_product_title": "De Cecco Rigatoni, No. 24",
      "product_url": "https://www.instacart.com/products/24756",
      "store_name": "wegmans",
      "product_id": "24756",
      "mapping_status": "suggested",
      "confidence": 0.82,
      "review_required": true,
      "availability": "unknown",
      "mapping_id": 1,
      "mapping_reason": "Best historical match."
    }
  ]
}
```

## Mappings

```http
GET /v1/mappings?status=suggested
PATCH /v1/mappings/{mapping_id}
```

Patch request:

```json
{
  "status": "approved",
  "selected_product_id": "24756",
  "hint": "Prefer De Cecco for dried pasta."
}
```

## Product Search

```http
GET /v1/products?q=rigatoni
```

Returns historical product candidates without exposing order URLs, payment
methods, account email paths, or shipping addresses.

## Recommend Products For A Planner Plan

```http
POST /v1/plans/{plan_id}/recommendations
```

When `MEALIE_PLANNER_BASE_URL` is configured, this fetches:

```text
{MEALIE_PLANNER_BASE_URL}/v1/plans/{plan_id}/ingredients
```

Then it recommends Instacart products for the returned consolidated ingredient
rows.
