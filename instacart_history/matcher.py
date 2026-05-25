from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field

from instacart_history.repository import ProductCandidate


@dataclass(frozen=True)
class MatchDecision:
    selected_product_id: str | None
    confidence: float
    reason: str
    review_required: bool


class IngredientMatcher(Protocol):
    def choose(
        self,
        *,
        ingredient: dict[str, Any],
        candidates: list[ProductCandidate],
        hint: str | None,
    ) -> MatchDecision:
        ...


class MatchResponse(BaseModel):
    selected_product_id: str | None = Field(description="The product_id from candidates, or null if no candidate fits.")
    confidence: float = Field(ge=0, le=1)
    reason: str
    review_required: bool


class OpenAIIngredientMatcher:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 30) -> None:
        self.client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        self.model = model

    def choose(
        self,
        *,
        ingredient: dict[str, Any],
        candidates: list[ProductCandidate],
        hint: str | None,
    ) -> MatchDecision:
        if not candidates:
            return MatchDecision(None, 0.0, "No historical products matched this ingredient.", True)
        payload = {
            "ingredient": ingredient,
            "hint": hint,
            "candidates": [
                {
                    "product_id": candidate.product_id,
                    "title": candidate.title,
                    "store_name": candidate.store_name,
                    "purchase_count": candidate.purchase_count,
                    "latest_order_date": candidate.latest_order_date,
                }
                for candidate in candidates
            ],
        }
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Match a meal-plan ingredient to the historically purchased Instacart product "
                        "Joe is most likely to want. Prefer exact staple matches, product titles with "
                        "the right form or package, higher purchase frequency, and recent purchases. "
                        "Return review_required true for ambiguity, weak matches, substitutions, or "
                        "anything a human should approve before reuse."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, sort_keys=True)},
            ],
            text_format=MatchResponse,
        )
        parsed = response.output_parsed
        return MatchDecision(
            selected_product_id=parsed.selected_product_id,
            confidence=parsed.confidence,
            reason=parsed.reason,
            review_required=parsed.review_required,
        )
