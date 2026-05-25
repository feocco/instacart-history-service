from instacart_history.matcher import MatchDecision
from instacart_history.repository import HistoryRepository
from instacart_history.service import RecommendationService


class RecordingMatcher:
    def __init__(self, decision: MatchDecision):
        self.decision = decision
        self.calls = []

    def choose(self, *, ingredient, candidates, hint):
        self.calls.append({"ingredient": ingredient, "candidates": candidates, "hint": hint})
        return self.decision


def add_product(repo: HistoryRepository, product_id: str, title: str, *, order_date: str = "2026-01-01") -> None:
    repo.upsert_order(
        account_label="acct/family",
        order_id=f"order-{product_id}",
        order_date=order_date,
        store_name="wegmans",
        currency="USD",
        grand_total=10.0,
        raw_payload={},
    )
    repo.upsert_order_item(
        account_label="acct/family",
        order_id=f"order-{product_id}",
        line_key=f"line-{product_id}",
        order_date=order_date,
        store_name="wegmans",
        product_id=product_id,
        title=title,
        quantity=1.0,
        price_paid=10.0,
        product_url=f"https://www.instacart.com/products/{product_id}",
        image_url=None,
        raw_payload={},
    )


def test_exact_historical_staple_maps_cleanly(tmp_path) -> None:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    add_product(repo, "eggs-18", "Wegmans Grade AA Large Eggs, 18 Count")
    matcher = RecordingMatcher(MatchDecision("eggs-18", 0.94, "Exact staple.", False))

    result = RecommendationService(repo=repo, matcher=matcher).recommend([{"food_name": "eggs"}])

    assert result["ingredients"][0]["recommended_product_title"] == "Wegmans Grade AA Large Eggs, 18 Count"
    assert result["ingredients"][0]["review_required"] is False


def test_ambiguous_ingredients_are_flagged_for_review(tmp_path) -> None:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    add_product(repo, "beans-black", "Goya Black Beans")
    add_product(repo, "beans-butter", "Wegmans Butter Beans")
    matcher = RecordingMatcher(MatchDecision("beans-black", 0.55, "Ambiguous bean request.", True))

    result = RecommendationService(repo=repo, matcher=matcher).recommend([{"food_name": "beans"}])

    assert result["ingredients"][0]["review_required"] is True
    assert result["ingredients"][0]["confidence"] == 0.55


def test_rejected_mappings_are_not_reused(tmp_path) -> None:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    add_product(repo, "old", "Wrong Rigatoni")
    add_product(repo, "new", "De Cecco Rigatoni, No. 24")
    repo.save_mapping(
        ingredient_key="rigatoni",
        ingredient_text="rigatoni",
        selected_product_id="old",
        status="rejected",
        confidence=0.2,
        reason="Wrong item.",
        hint=None,
        source="manual",
    )
    matcher = RecordingMatcher(MatchDecision("new", 0.88, "Better match.", False))

    result = RecommendationService(repo=repo, matcher=matcher).recommend([{"food_name": "rigatoni"}])

    assert result["ingredients"][0]["product_id"] == "new"
    assert matcher.calls
