from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from instacart_history.importer import InstacartCsvImporter
from instacart_history.repository import HistoryRepository, IngredientMapping, ProductCandidate, Staple
from instacart_history.service import RecommendationService


class ImportRequest(BaseModel):
    data_dir: str = "/Users/feocco/code/grocery-research/data/instacart"


class ImportFilePayload(BaseModel):
    relative_path: str
    content: str


class ImportFilesRequest(BaseModel):
    files: list[ImportFilePayload]


class IngredientsRequest(BaseModel):
    include_staples: bool = False
    ingredients: list[dict[str, Any]] | None = None
    consolidated: list[dict[str, Any]] | None = None
    by_recipe: list[dict[str, Any]] | None = None


class PlanRecommendationRequest(BaseModel):
    include_staples: bool = False
    planner_ingredients: dict[str, Any] | None = None


class StapleCreateRequest(BaseModel):
    scope: str = Field(pattern="^(ingredient_text|ingredient_key|product_id)$")
    value: str
    label: str
    source: str = Field(default="manual", pattern="^(seed|manual|llm)$")


class StapleUpdateRequest(BaseModel):
    scope: str | None = Field(default=None, pattern="^(ingredient_text|ingredient_key|product_id)$")
    value: str | None = None
    label: str | None = None
    active: bool | None = None
    source: str | None = Field(default=None, pattern="^(seed|manual|llm)$")


class MappingUpdateRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(approved|suggested|rejected|needs_review)$")
    selected_product_id: str | None = None
    hint: str | None = None
    reason: str | None = None


def create_app(service: RecommendationService) -> FastAPI:
    app = FastAPI(
        title="Instacart History Service",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi_json() -> dict[str, Any]:
        return app.openapi()

    @app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
    async def docs() -> str:
        return render_docs_page(app)

    @app.post("/v1/import/instacart-csv")
    async def import_instacart_csv(request: ImportRequest) -> dict[str, int]:
        data_dir = Path(request.data_dir)
        if not data_dir.exists():
            raise HTTPException(status_code=404, detail="data_dir not found")
        result = InstacartCsvImporter(service.repo).import_directory(data_dir)
        return {
            "files_seen": result.files_seen,
            "orders_created": result.orders_created,
            "orders_updated": result.orders_updated,
            "items_created": result.items_created,
            "items_updated": result.items_updated,
            "rows_skipped": result.rows_skipped,
        }

    @app.post("/v1/import/instacart-csv-files")
    async def import_instacart_csv_files(request: ImportFilesRequest) -> dict[str, int]:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for file_payload in request.files:
                relative = Path(file_payload.relative_path)
                if relative.is_absolute() or ".." in relative.parts:
                    raise HTTPException(status_code=422, detail="relative_path must stay inside the upload root")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(file_payload.content, encoding="utf-8")
            result = InstacartCsvImporter(service.repo).import_directory(root)
        return {
            "files_seen": result.files_seen,
            "orders_created": result.orders_created,
            "orders_updated": result.orders_updated,
            "items_created": result.items_created,
            "items_updated": result.items_updated,
            "rows_skipped": result.rows_skipped,
        }

    @app.post("/v1/recommendations/ingredients")
    async def recommend_ingredients(request: IngredientsRequest) -> dict[str, Any]:
        ingredients = flatten_ingredients(request)
        return await anyio.to_thread.run_sync(lambda: service.recommend(ingredients, include_staples=request.include_staples))

    @app.post("/v1/plans/{plan_id}/recommendations")
    async def recommend_plan(plan_id: str, request: PlanRecommendationRequest | None = None) -> dict[str, Any]:
        try:
            return await anyio.to_thread.run_sync(
                lambda: service.recommend_plan(
                    plan_id,
                    planner_ingredients=(request.planner_ingredients if request else None),
                    include_staples=(request.include_staples if request else False),
                )
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"planner lookup failed: {exc}") from exc

    @app.post("/v1/plans/{plan_id}/shopping-prompt", response_class=PlainTextResponse)
    async def shopping_prompt(plan_id: str, request: PlanRecommendationRequest | None = None) -> str:
        try:
            return await anyio.to_thread.run_sync(
                lambda: service.shopping_prompt(
                    plan_id,
                    planner_ingredients=(request.planner_ingredients if request else None),
                    include_staples=(request.include_staples if request else False),
                )
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"planner lookup failed: {exc}") from exc

    @app.get("/v1/mappings")
    async def list_mappings(status: str | None = None) -> list[dict[str, Any]]:
        if status and status not in {"approved", "suggested", "rejected", "needs_review"}:
            raise HTTPException(status_code=422, detail="invalid status")
        return [mapping_payload(service.repo, mapping) for mapping in service.repo.list_mappings(status=status)]

    @app.get("/v1/products")
    async def search_products(q: str, limit: int = 25) -> list[dict[str, Any]]:
        return [product_payload(product) for product in service.repo.find_products(q, limit=limit)]

    @app.get("/v1/staples")
    async def list_staples(active: bool | None = None) -> list[dict[str, Any]]:
        return [staple_payload(staple) for staple in service.repo.list_staples(active=active)]

    @app.post("/v1/staples")
    async def create_staple(request: StapleCreateRequest) -> dict[str, Any]:
        try:
            staple = service.repo.upsert_staple(
                scope=request.scope,
                value=request.value,
                label=request.label,
                source=request.source,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return staple_payload(staple)

    @app.patch("/v1/staples/{staple_id}")
    async def update_staple(staple_id: int, request: StapleUpdateRequest) -> dict[str, Any]:
        try:
            staple = service.repo.update_staple(
                staple_id,
                scope=request.scope,
                value=request.value,
                label=request.label,
                active=request.active,
                source=request.source,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="staple not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return staple_payload(staple)

    @app.delete("/v1/staples/{staple_id}")
    async def delete_staple(staple_id: int) -> dict[str, Any]:
        try:
            staple = service.repo.update_staple(staple_id, active=False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="staple not found") from exc
        return staple_payload(staple)

    @app.patch("/v1/mappings/{mapping_id}")
    async def update_mapping(mapping_id: int, request: MappingUpdateRequest) -> dict[str, Any]:
        if request.selected_product_id and service.repo.product_by_product_id(request.selected_product_id) is None:
            raise HTTPException(status_code=404, detail="selected product not found")
        try:
            mapping = service.repo.update_mapping(
                mapping_id,
                status=request.status,
                selected_product_id=request.selected_product_id,
                hint=request.hint,
                reason=request.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="mapping not found") from exc
        return mapping_payload(service.repo, mapping)

    @app.get("/admin", response_class=HTMLResponse)
    async def admin() -> str:
        mappings = service.repo.list_mappings()
        rows = "\n".join(admin_row(service.repo, mapping) for mapping in mappings)
        staple_rows = "\n".join(staple_row(staple) for staple in service.repo.list_staples())
        return (
            ADMIN_HTML.replace("{{ rows }}", rows or "<tr><td colspan='7'>No mappings yet.</td></tr>")
            .replace("{{ staple_rows }}", staple_rows or "<tr><td colspan='6'>No staples yet.</td></tr>")
        )

    return app


def render_docs_page(app: FastAPI) -> str:
    schema = app.openapi()
    path_sections: list[str] = []
    for path, operations in sorted(schema.get("paths", {}).items()):
        method_rows: list[str] = []
        for method, operation in sorted(operations.items()):
            summary = escape(str(operation.get("summary") or operation.get("operationId") or ""))
            description = escape(str(operation.get("description") or ""))
            method_rows.append(
                f"""
                <div class="operation">
                  <span class="verb verb-{escape(method)}">{escape(method.upper())}</span>
                  <div>
                    <strong>{summary}</strong>
                    <div class="description">{description}</div>
                  </div>
                </div>
                """
            )
        path_sections.append(
            f"""
            <section class="path-group">
              <h2>{escape(path)}</h2>
              {''.join(method_rows)}
            </section>
            """
        )

    return f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{escape(str(schema["info"]["title"]))} API</title>
      <style>
        :root {{
          color-scheme: light;
          --bg: #f6f7f8;
          --surface: #ffffff;
          --text: #172026;
          --muted: #5b6770;
          --border: #d6dbe0;
          --accent: #205493;
        }}
        body {{
          margin: 0;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          color: var(--text);
          background: var(--bg);
        }}
        main {{
          max-width: 1080px;
          margin: 0 auto;
          padding: 32px 20px 48px;
        }}
        header {{
          margin-bottom: 24px;
        }}
        h1 {{
          margin: 0 0 8px;
          font-size: 30px;
          line-height: 1.1;
        }}
        .summary {{
          margin: 0 0 10px;
          color: var(--muted);
        }}
        .links {{
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          margin-top: 12px;
        }}
        .links a {{
          color: var(--accent);
          text-decoration: none;
          font-weight: 600;
        }}
        .meta {{
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          color: var(--muted);
          font-size: 14px;
        }}
        .path-group {{
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 16px 18px;
          margin: 0 0 14px;
        }}
        .path-group h2 {{
          margin: 0 0 12px;
          font-size: 18px;
          word-break: break-word;
        }}
        .operation {{
          display: grid;
          grid-template-columns: auto 1fr;
          gap: 12px;
          align-items: start;
          padding: 10px 0;
          border-top: 1px solid var(--border);
        }}
        .operation:first-of-type {{
          border-top: 0;
          padding-top: 0;
        }}
        .verb {{
          display: inline-block;
          min-width: 66px;
          padding: 2px 8px;
          border-radius: 999px;
          text-align: center;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0;
          color: #fff;
          background: #52616b;
        }}
        .verb-get {{ background: #2f855a; }}
        .verb-post {{ background: #2b6cb0; }}
        .verb-patch {{ background: #b7791f; }}
        .verb-delete {{ background: #c53030; }}
        .description {{
          margin-top: 4px;
          color: var(--muted);
          font-size: 14px;
          white-space: pre-wrap;
        }}
      </style>
    </head>
    <body>
      <main>
        <header>
          <h1>{escape(str(schema["info"]["title"]))} API</h1>
          <p class="summary">{escape(str(schema.get("info", {}).get("description") or "Self-contained browser docs for the service HTTP API."))}</p>
          <div class="meta">
            <span>OpenAPI {escape(str(schema.get("openapi", "")))}</span>
            <span>{len(schema.get("paths", {}))} paths</span>
          </div>
          <div class="links">
            <a href="/openapi.json">OpenAPI JSON</a>
            <a href="/health">Health check</a>
          </div>
        </header>
        {''.join(path_sections)}
      </main>
    </body>
    </html>
    """


def flatten_ingredients(request: IngredientsRequest) -> list[dict[str, Any]]:
    if request.ingredients is not None:
        return request.ingredients
    if request.consolidated is not None:
        return request.consolidated
    if request.by_recipe is not None:
        ingredients: list[dict[str, Any]] = []
        for recipe in request.by_recipe:
            for ingredient in recipe.get("ingredients", []):
                ingredients.append({**ingredient, "source_recipe": recipe.get("recipe_title")})
        return ingredients
    raise HTTPException(status_code=422, detail="ingredients, consolidated, or by_recipe is required")


def mapping_payload(repo: HistoryRepository, mapping: IngredientMapping) -> dict[str, Any]:
    product = repo.product_by_product_id(mapping.selected_product_id) if mapping.selected_product_id else None
    return {
        "id": mapping.id,
        "ingredient_key": mapping.ingredient_key,
        "ingredient_text": mapping.ingredient_text,
        "selected_product_id": mapping.selected_product_id,
        "selected_product_title": product.title if product else None,
        "status": mapping.status,
        "confidence": mapping.confidence,
        "reason": mapping.reason,
        "hint": mapping.hint,
        "source": mapping.source,
        "created_at": mapping.created_at,
        "updated_at": mapping.updated_at,
    }


def product_payload(product: ProductCandidate) -> dict[str, Any]:
    return {
        "product_id": product.product_id,
        "title": product.title,
        "store_name": product.store_name,
        "product_url": product.product_url,
        "purchase_count": product.purchase_count,
        "latest_order_date": product.latest_order_date,
    }


def staple_payload(staple: Staple) -> dict[str, Any]:
    return {
        "id": staple.id,
        "scope": staple.scope,
        "value": staple.value,
        "label": staple.label,
        "active": staple.active,
        "source": staple.source,
        "created_at": staple.created_at,
        "updated_at": staple.updated_at,
    }


def product_label(product: ProductCandidate | None) -> str:
    if product is None:
        return ""
    return escape(product.title)


def admin_row(repo: HistoryRepository, mapping: IngredientMapping) -> str:
    product = repo.product_by_product_id(mapping.selected_product_id) if mapping.selected_product_id else None
    return f"""
    <tr>
      <td>{mapping.id}</td>
      <td>{escape(mapping.ingredient_text)}</td>
      <td>{product_label(product)}</td>
      <td>{escape(mapping.status)}</td>
      <td>{mapping.confidence if mapping.confidence is not None else ""}</td>
      <td>{escape(mapping.hint or "")}</td>
      <td>
        <form onsubmit="return updateMapping(event, {mapping.id})">
          <select name="status">
            {status_options(mapping.status)}
          </select>
          <input name="selected_product_id" value="{escape(mapping.selected_product_id or "")}" placeholder="product id">
          <input name="hint" value="{escape(mapping.hint or "")}" placeholder="hint">
          <button type="submit">Save</button>
        </form>
      </td>
    </tr>
    """


def status_options(current: str) -> str:
    options = []
    for status in ("approved", "suggested", "rejected", "needs_review"):
        selected = " selected" if status == current else ""
        options.append(f'<option value="{status}"{selected}>{status}</option>')
    return "\n".join(options)


def staple_row(staple: Staple) -> str:
    return f"""
    <tr>
      <td>{staple.id}</td>
      <td>{escape(staple.label)}</td>
      <td>{escape(staple.scope)}</td>
      <td>{escape(staple.value)}</td>
      <td>{'yes' if staple.active else 'no'}</td>
      <td>
        <form onsubmit="return updateStaple(event, {staple.id})">
          <input name="label" value="{escape(staple.label)}" placeholder="label">
          <select name="scope">
            {staple_scope_options(staple.scope)}
          </select>
          <input name="value" value="{escape(staple.value)}" placeholder="value">
          <label><input type="checkbox" name="active" {'checked' if staple.active else ''}> active</label>
          <button type="submit">Save</button>
        </form>
      </td>
    </tr>
    """


def staple_scope_options(current: str) -> str:
    options = []
    for scope in ("ingredient_text", "ingredient_key", "product_id"):
        selected = " selected" if scope == current else ""
        options.append(f'<option value="{scope}"{selected}>{scope}</option>')
    return "\n".join(options)


def escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


ADMIN_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Instacart Mappings</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; color: #172026; background: #f7f7f4; }
    h1 { font-size: 24px; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; background: white; }
    th, td { border-bottom: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }
    th { background: #ecece6; }
    form { display: flex; gap: 6px; flex-wrap: wrap; }
    input, select, button { font: inherit; padding: 6px; }
    button { cursor: pointer; }
  </style>
</head>
<body>
  <h1>Instacart Ingredient Mappings</h1>
  <section>
    <form onsubmit="return searchProducts(event)">
      <input name="q" placeholder="Search historical products">
      <button type="submit">Search</button>
    </form>
    <div id="product-results"></div>
  </section>
  <section>
    <h2>Staples</h2>
    <form onsubmit="return createStaple(event)">
      <input name="label" placeholder="label">
      <select name="scope">
        <option value="ingredient_text">ingredient_text</option>
        <option value="ingredient_key">ingredient_key</option>
        <option value="product_id">product_id</option>
      </select>
      <input name="value" placeholder="value">
      <button type="submit">Add staple</button>
    </form>
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Label</th>
          <th>Scope</th>
          <th>Value</th>
          <th>Active</th>
          <th>Edit</th>
        </tr>
      </thead>
      <tbody>
        {{ staple_rows }}
      </tbody>
    </table>
  </section>
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Ingredient</th>
        <th>Product</th>
        <th>Status</th>
        <th>Confidence</th>
        <th>Hint</th>
        <th>Edit</th>
      </tr>
    </thead>
    <tbody>
      {{ rows }}
    </tbody>
  </table>
  <script>
    async function updateMapping(event, id) {
      event.preventDefault();
      const form = event.target;
      const payload = {
        status: form.status.value,
        selected_product_id: form.selected_product_id.value || null,
        hint: form.hint.value || null
      };
      const response = await fetch(`/v1/mappings/${id}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        alert(await response.text());
        return false;
      }
      window.location.reload();
      return false;
    }
    async function createStaple(event) {
      event.preventDefault();
      const form = event.target;
      const payload = {
        label: form.label.value,
        scope: form.scope.value,
        value: form.value.value,
        source: "manual"
      };
      const response = await fetch("/v1/staples", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        alert(await response.text());
        return false;
      }
      window.location.reload();
      return false;
    }
    async function updateStaple(event, id) {
      event.preventDefault();
      const form = event.target;
      const payload = {
        label: form.label.value,
        scope: form.scope.value,
        value: form.value.value,
        active: form.active.checked
      };
      const response = await fetch(`/v1/staples/${id}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        alert(await response.text());
        return false;
      }
      window.location.reload();
      return false;
    }
    async function searchProducts(event) {
      event.preventDefault();
      const q = event.target.q.value;
      const response = await fetch(`/v1/products?q=${encodeURIComponent(q)}`);
      const products = await response.json();
      document.getElementById("product-results").innerHTML = products.map((product) => (
        `<p><code>${product.product_id}</code> ${product.title} ` +
        `<small>${product.store_name || ""} ${product.purchase_count} purchases</small></p>`
      )).join("") || "<p>No products found.</p>";
      return false;
    }
  </script>
</body>
</html>
"""
