from __future__ import annotations

from typing import Any

import httpx

from instacart_history.matcher import IngredientMatcher
from instacart_history.repository import HistoryRepository, IngredientMapping, ProductCandidate, normalize_for_search


class RecommendationService:
    def __init__(
        self,
        *,
        repo: HistoryRepository,
        matcher: IngredientMatcher,
        planner_base_url: str | None = None,
    ) -> None:
        self.repo = repo
        self.matcher = matcher
        self.planner_base_url = planner_base_url.rstrip("/") if planner_base_url else None

    def recommend(self, ingredients: list[dict[str, Any]]) -> dict[str, Any]:
        return {"ingredients": [self._recommend_one(ingredient) for ingredient in ingredients]}

    def recommend_plan(self, plan_id: str, *, planner_ingredients: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = planner_ingredients if planner_ingredients is not None else self.fetch_plan_ingredients(plan_id)
        ingredients = payload.get("consolidated")
        if not isinstance(ingredients, list):
            ingredients = []
            for recipe in payload.get("by_recipe") or []:
                if isinstance(recipe, dict):
                    for ingredient in recipe.get("ingredients") or []:
                        if isinstance(ingredient, dict):
                            ingredients.append({**ingredient, "source_recipe": recipe.get("recipe_title")})
        result = self.recommend(ingredients)
        return {
            "plan_id": payload.get("plan_id", plan_id),
            "planner_status": payload.get("status"),
            **result,
        }

    def fetch_plan_ingredients(self, plan_id: str) -> dict[str, Any]:
        if not self.planner_base_url:
            raise RuntimeError("MEALIE_PLANNER_BASE_URL is required for plan recommendation lookups")
        response = httpx.get(
            f"{self.planner_base_url}/v1/plans/{plan_id}/ingredients",
            timeout=30,
            trust_env=False,
        )
        response.raise_for_status()
        return response.json()

    def _recommend_one(self, ingredient: dict[str, Any]) -> dict[str, Any]:
        ingredient_text = ingredient_text_for(ingredient)
        ingredient_key = ingredient_key_for(ingredient)
        saved = self.repo.latest_mapping(
            ingredient_key,
            statuses=["approved", "suggested", "needs_review", "rejected"],
        )
        if saved and saved.status != "rejected":
            product = self.repo.product_by_product_id(saved.selected_product_id) if saved.selected_product_id else None
            return annotated(ingredient, product, saved, review_required=saved.status != "approved")

        candidates = self.repo.find_products(ingredient_text or ingredient_key, limit=20)
        decision = self.matcher.choose(ingredient=ingredient, candidates=candidates, hint=saved.hint if saved else None)
        product = self.repo.product_by_product_id(decision.selected_product_id) if decision.selected_product_id else None
        status = "needs_review" if product is None else "suggested"
        mapping = self.repo.save_mapping(
            ingredient_key=ingredient_key,
            ingredient_text=ingredient_text,
            selected_product_id=decision.selected_product_id,
            status=status,
            confidence=decision.confidence,
            reason=decision.reason,
            hint=saved.hint if saved else None,
            source="llm",
        )
        self.repo.record_attempt(
            ingredient_key=ingredient_key,
            llm_input={
                "ingredient": ingredient,
                "hint": saved.hint if saved else None,
                "candidates": [candidate_payload(candidate) for candidate in candidates],
            },
            llm_output={
                "selected_product_id": decision.selected_product_id,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "review_required": decision.review_required,
            },
            selected_product_id=decision.selected_product_id,
            confidence=decision.confidence,
            reason=decision.reason,
            review_required=decision.review_required,
        )
        return annotated(ingredient, product, mapping, review_required=decision.review_required or status != "suggested")


def ingredient_text_for(ingredient: dict[str, Any]) -> str:
    for key in ("food_name", "display", "originalText", "note"):
        value = ingredient.get(key)
        if value:
            return str(value)
    food = ingredient.get("food")
    if isinstance(food, dict) and food.get("name"):
        return str(food["name"])
    return "unknown ingredient"


def ingredient_key_for(ingredient: dict[str, Any]) -> str:
    food_id = ingredient.get("food_id")
    if food_id:
        return str(food_id)
    food = ingredient.get("food")
    if isinstance(food, dict) and food.get("id"):
        return str(food["id"])
    return normalize_for_search(ingredient_text_for(ingredient)).replace(" ", "_") or "unknown_ingredient"


def candidate_payload(candidate: ProductCandidate) -> dict[str, Any]:
    return {
        "product_id": candidate.product_id,
        "title": candidate.title,
        "store_name": candidate.store_name,
        "purchase_count": candidate.purchase_count,
        "latest_order_date": candidate.latest_order_date,
    }


def annotated(
    ingredient: dict[str, Any],
    product: ProductCandidate | None,
    mapping: IngredientMapping,
    *,
    review_required: bool,
) -> dict[str, Any]:
    return {
        **ingredient,
        "recommended_product_title": product.title if product else None,
        "product_url": product.product_url if product else None,
        "store_name": product.store_name if product else None,
        "product_id": product.product_id if product else mapping.selected_product_id,
        "mapping_status": mapping.status,
        "confidence": mapping.confidence,
        "review_required": review_required,
        "availability": "unknown",
        "mapping_id": mapping.id,
        "mapping_reason": mapping.reason,
    }
