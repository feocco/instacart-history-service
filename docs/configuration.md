# Configuration

The service reads `.env.local` first, then `.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `DATA_DIR` | `data` | Directory for `instacart_history.sqlite3`. |
| `OPENAI_API_KEY` | required | Required for unmapped ingredient matching. |
| `OPENAI_MODEL` | `gpt-5-mini` | Model used for structured product matching. |
| `OPENAI_TIMEOUT_SECONDS` | `30` | Per-request timeout for OpenAI matching calls. |
| `MEALIE_PLANNER_BASE_URL` | unset | Optional planner API base URL for `POST /v1/plans/{plan_id}/recommendations`. On Mac mini containers, use `http://host.docker.internal:8097`. |
| `HOST` | `0.0.0.0` | Uvicorn bind host. |
| `PORT` | `8095` | Uvicorn port. |

The SQLite database is created at:

```text
${DATA_DIR}/instacart_history.sqlite3
```

CSV import is explicit. The service does not watch folders or call Instacart in
v1. Re-run the import endpoint after downloading newer exports.
