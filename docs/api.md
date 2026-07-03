# API

The service exposes browser-friendly docs at `GET /docs` and the machine-readable
OpenAPI schema at `GET /openapi.json`.

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
  "include_staples": false,
  "ingredients": [
    {"food_name": "rigatoni", "quantity": 1, "unit_name": "box"}
  ]
}
```

The endpoint also accepts a top-level `consolidated` array or `by_recipe` array
from `mealie-planner`. Active staples are excluded by default; set
`include_staples` to `true` to keep them.

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

## Staples

```http
GET /v1/staples
POST /v1/staples
PATCH /v1/staples/{staple_id}
DELETE /v1/staples/{staple_id}
```

Staples are stored separately from mappings. They can match either normalized
ingredient text, ingredient keys, or product ids. Deletes are soft deletes that
set `active` to `false`.

Create request:

```json
{
  "scope": "ingredient_text",
  "value": "olive oil",
  "label": "olive oil",
  "source": "manual"
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
rows. Request bodies accept `include_staples`, defaulting to `false`.

Saved `approved`, `suggested`, and `needs_review` mappings are reused on later
runs so first-pass LLM suggestions stay stable. `suggested` and `needs_review`
rows still return `review_required: true`; rejected mappings are not reused.

## Shopping Prompt

```http
POST /v1/plans/{plan_id}/shopping-prompt
```

Request:

```json
{"include_staples": false}
```

This returns `text/plain` suitable for pasting into ChatGPT with Instacart:

```text
Please create me an Instacart order with the items and quantities below. Use the specific product names when provided.

- Wegmans Organic Extra Firm Tofu — 1 14-oz package
```

Use `plan_id=latest` to fetch the latest accepted planner plan. The prompt omits
mapping metadata, URLs, confidence, and review fields.
