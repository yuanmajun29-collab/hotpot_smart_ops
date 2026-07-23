"""Cloud-side cross-store analytics for Hotpot Platform."""

from hotpot_platform.analytics.ai_suggestions import SuggestionEngine
from hotpot_platform.analytics.store_compare import StoreCompareEngine
from hotpot_platform.analytics.trend_engine import TrendEngine

__all__ = ["StoreCompareEngine", "TrendEngine", "SuggestionEngine"]
