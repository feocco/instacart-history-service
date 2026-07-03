# Instacart History Service

FastAPI service for importing Instacart CSV exports, storing purchase history in
SQLite, and mapping meal-plan ingredients to the specific products Joe normally
buys.

## Quickstart

```bash
uv sync --extra dev
cp .env.example .env.local
uv run instacart-history
```

The service listens on `http://localhost:8095` by default.

Browse the built-in docs at `http://localhost:8095/docs` and fetch the schema
at `http://localhost:8095/openapi.json`.

Import the current exports:

```bash
curl -X POST http://localhost:8095/v1/import/instacart-csv \
  -H 'Content-Type: application/json' \
  -d '{"data_dir":"/Users/feocco/code/grocery-research/data/instacart"}'
```

Send ingredients from `mealie-planner`:

```bash
curl -X POST http://localhost:8095/v1/recommendations/ingredients \
  -H 'Content-Type: application/json' \
  -d '{"ingredients":[{"food_name":"rigatoni","quantity":1,"unit_name":"box"}]}'
```

Generate the copy/paste prompt for the latest accepted planner plan:

```bash
curl -X POST http://localhost:8095/v1/plans/latest/shopping-prompt \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Review suggested mappings and staples at `http://localhost:8095/admin`.

## Docs

- [Configuration](docs/configuration.md)
- [API](docs/api.md)
- [Security](docs/security.md)
