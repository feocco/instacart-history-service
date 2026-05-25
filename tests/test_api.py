from fastapi.testclient import TestClient

from instacart_history.api import create_app
from instacart_history.matcher import MatchDecision
from instacart_history.repository import HistoryRepository
from instacart_history.service import RecommendationService


class FakeMatcher:
    def __init__(self):
        self.calls = []

    def choose(self, *, ingredient, candidates, hint):
        self.calls.append((ingredient, candidates, hint))
        return MatchDecision(
            selected_product_id=candidates[0].product_id,
            confidence=0.82,
            reason="Best historical match.",
            review_required=True,
        )


def seed_product(repo: HistoryRepository, *, product_id: str = "24756", title: str = "De Cecco Rigatoni, No. 24") -> None:
    repo.upsert_order(
        account_label="local/family",
        order_id="order-1",
        order_date="2026-02-05",
        store_name="wegmans",
        currency="USD",
        grand_total=34.29,
        raw_payload={"Order URL": "https://order.example", "Payment Methods": "Visa 1111"},
    )
    repo.upsert_order_item(
        account_label="local/family",
        order_id="order-1",
        line_key=f"order-1:{product_id}:0",
        order_date="2026-02-05",
        store_name="wegmans",
        product_id=product_id,
        title=title,
        quantity=1.0,
        price_paid=3.49,
        product_url=f"https://www.instacart.com/products/{product_id}",
        image_url="https://image.example/item.jpg",
        raw_payload={"Shipping Address (item)": "1 Loop Road"},
    )


def client_for(tmp_path, matcher=None) -> tuple[TestClient, HistoryRepository, FakeMatcher]:
    repo = HistoryRepository(tmp_path / "history.sqlite3")
    fake = matcher or FakeMatcher()
    app = create_app(RecommendationService(repo=repo, matcher=fake))
    return TestClient(app), repo, fake


def test_health_endpoint(tmp_path) -> None:
    client, _, _ = client_for(tmp_path)

    assert client.get("/health").json() == {"status": "ok"}


def test_recommendation_uses_approved_mapping_without_calling_llm(tmp_path) -> None:
    client, repo, matcher = client_for(tmp_path)
    seed_product(repo)
    repo.save_mapping(
        ingredient_key="rigatoni",
        ingredient_text="rigatoni",
        selected_product_id="24756",
        status="approved",
        confidence=1.0,
        reason="Manual choice.",
        hint="prefer De Cecco",
        source="manual",
    )

    response = client.post("/v1/recommendations/ingredients", json={"ingredients": [{"food_name": "rigatoni"}]})

    assert response.status_code == 200
    item = response.json()["ingredients"][0]
    assert item["recommended_product_title"] == "De Cecco Rigatoni, No. 24"
    assert item["mapping_status"] == "approved"
    assert item["availability"] == "unknown"
    assert matcher.calls == []
    assert "order.example" not in response.text
    assert "Loop Road" not in response.text


def test_recommendation_calls_llm_and_persists_suggested_mapping(tmp_path) -> None:
    client, repo, matcher = client_for(tmp_path)
    seed_product(repo)

    response = client.post("/v1/recommendations/ingredients", json={"ingredients": [{"food_name": "rigatoni"}]})

    assert response.status_code == 200
    item = response.json()["ingredients"][0]
    assert item["recommended_product_title"] == "De Cecco Rigatoni, No. 24"
    assert item["mapping_status"] == "suggested"
    assert item["review_required"] is True
    assert len(matcher.calls) == 1
    mappings = repo.list_mappings(status="suggested")
    assert mappings[0].ingredient_key == "rigatoni"
    assert mappings[0].selected_product_id == "24756"
    assert repo.list_attempts()[0].llm_output["selected_product_id"] == "24756"


def test_mapping_edit_endpoint_updates_status_product_and_hint(tmp_path) -> None:
    client, repo, _ = client_for(tmp_path)
    seed_product(repo)
    seed_product(repo, product_id="999", title="Wegmans Rigatoni")
    mapping = repo.save_mapping(
        ingredient_key="rigatoni",
        ingredient_text="rigatoni",
        selected_product_id="24756",
        status="suggested",
        confidence=0.8,
        reason="Initial.",
        hint=None,
        source="llm",
    )

    response = client.patch(
        f"/v1/mappings/{mapping.id}",
        json={"status": "approved", "selected_product_id": "999", "hint": "Prefer store brand when cheaper."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["selected_product_id"] == "999"
    assert payload["hint"] == "Prefer store brand when cheaper."


def test_product_search_endpoint_returns_history_without_sensitive_fields(tmp_path) -> None:
    client, repo, _ = client_for(tmp_path)
    seed_product(repo)

    response = client.get("/v1/products", params={"q": "rigatoni"})

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["product_id"] == "24756"
    assert payload["title"] == "De Cecco Rigatoni, No. 24"
    assert "account" not in payload
    assert "raw_payload" not in payload
    assert "Loop Road" not in response.text


def test_plan_recommendations_fetches_planner_ingredients(tmp_path) -> None:
    client, repo, matcher = client_for(tmp_path)
    seed_product(repo)

    response = client.post(
        "/v1/plans/plan-1/recommendations",
        json={
            "planner_ingredients": {
                "plan_id": "plan-1",
                "consolidated": [{"food_name": "rigatoni", "quantity": 1, "unit_name": "box"}],
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["plan_id"] == "plan-1"
    assert response.json()["ingredients"][0]["recommended_product_title"] == "De Cecco Rigatoni, No. 24"
    assert len(matcher.calls) == 1


def test_admin_page_loads_and_includes_suggested_mapping(tmp_path) -> None:
    client, repo, _ = client_for(tmp_path)
    seed_product(repo)
    repo.save_mapping(
        ingredient_key="rigatoni",
        ingredient_text="rigatoni",
        selected_product_id="24756",
        status="suggested",
        confidence=0.8,
        reason="Initial.",
        hint=None,
        source="llm",
    )

    response = client.get("/admin")

    assert response.status_code == 200
    assert "rigatoni" in response.text
    assert "De Cecco Rigatoni" in response.text
