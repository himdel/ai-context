from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from api.harness.claude import _accumulate_usage, _empty_totals
from api.models import ConversationIndex
from api.views import stats


class ModelCostAccumulationTests(TestCase):
    def test_claude_costs_are_grouped_by_request_model(self):
        totals = _empty_totals()
        seen = set()
        sonnet = {
            "type": "assistant",
            "requestId": "request-sonnet",
            "message": {
                "model": "claude-sonnet-4",
                "usage": {"input_tokens": 1000000, "output_tokens": 100000},
            },
        }
        opus = {
            "type": "assistant",
            "requestId": "request-opus",
            "message": {
                "model": "claude-opus-4",
                "usage": {"input_tokens": 100000, "output_tokens": 10000},
            },
        }

        _accumulate_usage(sonnet, totals, seen)
        _accumulate_usage(sonnet, totals, seen)
        _accumulate_usage(opus, totals, seen)

        self.assertEqual(totals["cost_usd"], 5.25)
        self.assertEqual(
            totals["cost_by_model"],
            {"claude-sonnet-4": 4.5, "claude-opus-4": 0.75},
        )


class ModelCostStatsTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        ConversationIndex.objects.create(
            conversation_id="sonnet",
            first_timestamp="2026-11-27T10:00:00Z",
            project="/work/one",
            message_count=2,
            cost_usd=3.0,
            cost_by_model={"claude-sonnet-4": 3.0},
        )
        ConversationIndex.objects.create(
            conversation_id="opus",
            first_timestamp="2026-11-27T11:00:00Z",
            project="/work/two",
            message_count=1,
            cost_usd=2.0,
            cost_by_model={"claude-opus-4": 2.0},
        )
        ConversationIndex.objects.create(
            conversation_id="legacy",
            first_timestamp="2026-11-27T12:00:00Z",
            project="/work/one",
            message_count=1,
            cost_usd=1.0,
            cost_by_model=None,
        )

    @patch("api.views._refresh_model_costs")
    def test_model_split_is_opt_in_and_keeps_total_cost(self, refresh):
        default_response = stats(self.factory.get("/api/stats/"))
        self.assertNotIn("model_costs", default_response.data)
        self.assertEqual(default_response.data["total_cost"], 6.0)
        refresh.assert_not_called()

        response = stats(self.factory.get("/api/stats/?split=model"))

        refresh.assert_called_once_with()
        self.assertEqual(response.data["total_cost"], 6.0)
        self.assertEqual(
            response.data["model_costs"],
            [
                {"model": "claude-sonnet-4", "cost": 3.0},
                {"model": "claude-opus-4", "cost": 2.0},
                {"model": "unknown", "cost": 1.0},
            ],
        )
