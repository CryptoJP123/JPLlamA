from __future__ import annotations

from app.intelligence.knowledge_library import is_customer_by_default
from app.intelligence.source_policy import plan_source_usage, requires_live_web_data


def test_direct_prompt_does_not_enable_sources():
    plan = plan_source_usage("Explain GitHub in simple terms.")
    assert plan.mode == "direct"
    assert plan.use_knowledge is False
    assert plan.use_web is False
    assert plan.use_reference_sources is False


def test_presentation_prompt_stays_direct_without_explicit_sources():
    plan = plan_source_usage("Make a 5-slide presentation explaining GitHub.")
    assert plan.mode == "direct"
    assert plan.use_knowledge is False
    assert plan.use_web is False


def test_explicit_knowledge_request_uses_knowledge_mode():
    plan = plan_source_usage("Check the knowledge base and summarize what we stored about VW RFQs.")
    assert plan.mode == "knowledge"
    assert plan.use_knowledge is True
    assert plan.use_web is False


def test_explicit_rfq_database_request_tracks_areas():
    plan = plan_source_usage("Build an RFQ review and use the RFQ Contract Review Knowledge Base, especially VW and Bayer.")
    assert plan.mode == "knowledge"
    assert plan.use_knowledge is True
    assert "rfq" in plan.requested_knowledge_areas
    assert "vw" in plan.requested_knowledge_areas
    assert "bayer" in plan.requested_knowledge_areas


def test_explicit_web_request_uses_web_only():
    plan = plan_source_usage("Search the web for the weather tomorrow in Rust Germany.")
    assert plan.mode == "web"
    assert plan.use_web is True
    assert plan.use_knowledge is False


def test_weather_without_web_request_stays_direct_and_requires_explicit_web():
    plan = plan_source_usage("What is the weather tomorrow in Rust Germany?")
    assert plan.mode == "direct"
    assert plan.use_web is False
    assert requires_live_web_data("What is the weather tomorrow in Rust Germany?") is True


def test_explicit_mixed_request_uses_knowledge_and_web():
    plan = plan_source_usage("Check my RFQ database for VW and search the web for current Volkswagen logistics news.")
    assert plan.mode == "mixed"
    assert plan.use_knowledge is True
    assert plan.use_web is True


def test_explicit_reference_request_uses_reference_mode():
    plan = plan_source_usage("Consult the DP World Freight Forwarding Documentation Centre and use the terms and conditions for this RFQ review.")
    assert plan.mode == "reference"
    assert plan.use_reference_sources is True
    assert "DP World Freight Forwarding Documentation Centre" in plan.requested_reference_sources


def test_company_classification_not_customer_by_default():
    assert is_customer_by_default("DP World") is False
    assert is_customer_by_default("Agility") is False
    assert is_customer_by_default("Cargo Partner") is False
    assert is_customer_by_default("Chain IQ") is False
    assert is_customer_by_default("CIQ") is False
    assert is_customer_by_default("AWK") is False
    assert is_customer_by_default("Eraneos") is False
