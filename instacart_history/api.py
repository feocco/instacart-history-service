from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from instacart_history.importer import InstacartCsvImporter
from instacart_history.repository import HistoryRepository, IngredientMapping, ProductCandidate
from instacart_history.service import RecommendationService


class ImportRequest(BaseModel):
    data_dir: str = "/Users/feocco/code/grocery-research/data/instacart"


class ImportFilePayload(BaseModel):
    relative_path: str
    content: str


class ImportFilesRequest(BaseModel):
    files: list[ImportFilePayload]


class IngredientsRequest(BaseModel):
    ingredients: list[dict[str, Any]] | None = None
    consolidated: list[dict[str, Any]] | None = None
    by_recipe: list[dict[str, Any]] | None = None


class PlanRecommendationRequest(BaseModel):
    planner_ingredients: dict[str, Any] | None = None


class MappingUpdateRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(approved|suggested|rejected|needs_review)$")
    selected_product_id: str | None = None
    hint: str | None = None
    reason: str | None = None


def create_app(service: RecommendationService) -> FastAPI:
    app = FastAPI(title="Instacart History Service", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
        return service.recommend(ingredients)

    @app.post("/v1/plans/{plan_id}/recommendations")
    async def recommend_plan(plan_id: str, request: PlanRecommendationRequest | None = None) -> dict[str, Any]:
        try:
            return service.recommend_plan(plan_id, planner_ingredients=(request.planner_ingredients if request else None))
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
        return ADMIN_HTML.replace("{{ rows }}", rows or "<tr><td colspan='7'>No mappings yet.</td></tr>")

    return app


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
