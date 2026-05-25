# Security

Instacart exports include sensitive local data:

- account identifiers from folder names
- order and invoice URLs
- shipping addresses
- payment-method fragments
- product/order history

The service stores raw CSV payloads locally in SQLite so import logic remains
auditable and future-proof, but recommendation and mapping APIs intentionally do
not expose raw payloads. Responses include product title, product URL, store,
product id, mapping state, and confidence only.

Keep `.env`, `.env.local`, `data/`, and SQLite database files out of git. The
provided `.gitignore` covers these paths.

V1 does not verify live Instacart availability and does not automate logged-in
Instacart browsing. The returned `availability` value is always `unknown`.
