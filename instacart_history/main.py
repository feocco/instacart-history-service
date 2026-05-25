from __future__ import annotations

import os

import uvicorn

from instacart_history.api import create_app
from instacart_history.config import AppConfig
from instacart_history.matcher import OpenAIIngredientMatcher
from instacart_history.repository import HistoryRepository
from instacart_history.service import RecommendationService


def build_service() -> RecommendationService:
    config = AppConfig.from_env()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    repo = HistoryRepository(config.db_path)
    matcher = OpenAIIngredientMatcher(
        api_key=config.openai_api_key,
        model=config.openai_model,
        timeout_seconds=config.openai_timeout_seconds,
    )
    return RecommendationService(
        repo=repo,
        matcher=matcher,
        planner_base_url=config.mealie_planner_base_url,
    )


app = create_app(build_service())


def main() -> None:
    uvicorn.run(
        "instacart_history.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8095")),
    )


if __name__ == "__main__":
    main()
