"""Events a registered webhook can subscribe to.

Receivers match on these exact names, so never rename one. Add new events here;
the API validation and the /webhooks UI both read from this dict.
"""

WEBHOOK_EVENTS: dict[str, str] = {
    "document.ingested_success": "Document parsed and stored",
    "document.ingested_failed": "Document could not be parsed",
    "intelligence.completed_success": "Tender report generated",
    "intelligence.completed_failed": "Tender report could not be generated",
    "relevance.analyzed_success": "Relevance verdict produced",
    "relevance.analyzed_failed": "Relevance analysis failed",
    "relevance.feedback_success": "Feedback recorded",
    "relevance.feedback_failed": "Feedback could not be recorded",
    "performance_cert.completed_success": "Performance certificates compared",
    "performance_cert.completed_failed": "Performance certificate comparison failed",
}
