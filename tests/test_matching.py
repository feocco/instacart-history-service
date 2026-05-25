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


def test_suggested_mapping_is_reused_for_stable_followup_results(tmp_path) -> None:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    add_product(repo, "rigatoni-1", "De Cecco Rigatoni, No. 24")
    repo.save_mapping(
        ingredient_key="rigatoni",
        ingredient_text="rigatoni",
        selected_product_id="rigatoni-1",
        status="suggested",
        confidence=0.82,
        reason="Initial LLM suggestion.",
        hint=None,
        source="llm",
    )
    matcher = RecordingMatcher(MatchDecision("wrong", 0.1, "Should not be called.", True))

    result = RecommendationService(repo=repo, matcher=matcher).recommend([{"food_name": "rigatoni"}])

    assert result["ingredients"][0]["product_id"] == "rigatoni-1"
    assert result["ingredients"][0]["mapping_status"] == "suggested"
    assert result["ingredients"][0]["review_required"] is True
    assert matcher.calls == []


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


def test_seeded_staples_are_idempotent_and_filter_by_ingredient_text(tmp_path) -> None:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    first_count = len(repo.list_staples())
    repo.seed_common_staples()

    assert len(repo.list_staples()) == first_count
    assert repo.is_staple(ingredient={"food_name": "olive oil"}, product_id=None) is True
    assert repo.is_staple(ingredient={"food_name": "rigatoni"}, product_id=None) is False


def test_inactive_staples_do_not_filter_items(tmp_path) -> None:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    staple = repo.upsert_staple(scope="ingredient_text", value="rice vinegar", label="rice vinegar", source="manual")

    assert repo.is_staple(ingredient={"food_name": "rice vinegar"}, product_id=None) is True

    repo.update_staple(staple.id, active=False)

    assert repo.is_staple(ingredient={"food_name": "rice vinegar"}, product_id=None) is False


def test_disabled_seeded_staples_stay_disabled_after_restart(tmp_path) -> None:
    db_path = tmp_path / "history.sqlite3"
    repo = HistoryRepository(db_path)
    olive_oil = next(staple for staple in repo.list_staples() if staple.label == "olive oil")

    repo.update_staple(olive_oil.id, active=False)
    restarted = HistoryRepository(db_path)

    assert restarted.is_staple(ingredient={"food_name": "olive oil"}, product_id=None) is False


def test_recommendations_exclude_staples_by_default_and_include_on_request(tmp_path) -> None:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    add_product(repo, "oil-1", "Wegmans Olive Oil")
    add_product(repo, "tofu-1", "Wegmans Organic Extra Firm Tofu")
    matcher = RecordingMatcher(MatchDecision("tofu-1", 0.9, "Tofu match.", False))
    service = RecommendationService(repo=repo, matcher=matcher)

    repo.save_mapping(
        ingredient_key="olive_oil",
        ingredient_text="olive oil",
        selected_product_id="oil-1",
        status="approved",
        confidence=1.0,
        reason="Manual.",
        hint=None,
        source="manual",
    )

    default_result = service.recommend([{"food_name": "olive oil"}, {"food_name": "tofu"}])
    include_result = service.recommend(
        [{"food_name": "olive oil"}, {"food_name": "tofu"}],
        include_staples=True,
    )

    assert [item["food_name"] for item in default_result["ingredients"]] == ["tofu"]
    assert [item["food_name"] for item in include_result["ingredients"]] == ["olive oil", "tofu"]


def test_product_id_staples_filter_mapped_items(tmp_path) -> None:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    add_product(repo, "broth-1", "Wegmans Culinary Vegetable Stock")
    repo.upsert_staple(scope="product_id", value="broth-1", label="vegetable stock", source="manual")
    repo.save_mapping(
        ingredient_key="vegetable_stock",
        ingredient_text="vegetable stock",
        selected_product_id="broth-1",
        status="approved",
        confidence=1.0,
        reason="Manual.",
        hint=None,
        source="manual",
    )
    matcher = RecordingMatcher(MatchDecision("broth-1", 1.0, "Should not be called.", False))

    result = RecommendationService(repo=repo, matcher=matcher).recommend([{"food_name": "vegetable stock"}])

    assert result["ingredients"] == []
    assert matcher.calls == []
