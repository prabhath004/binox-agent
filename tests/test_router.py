from app.router import classify_query


def test_cursor_queries_route_to_research_without_llm():
    assert classify_query("what is cursor") == "research"
    assert classify_query("cursor vs replit") == "research"


def test_non_product_cursor_queries_route_to_general():
    assert classify_query("sql cursor in postgres") == "general"
