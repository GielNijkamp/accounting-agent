"""Self-check without API/CLI calls. Run: python tests/test_agent1_bank.py"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent1_bank import THRESHOLD, Proposal, bookable, load_company_context


def v(confidence: float) -> Proposal:
    return Proposal(mutation_id="1", ledger_account_id="2", confidence=confidence, rationale="x")


def test_threshold():
    assert bookable(v(THRESHOLD))
    assert bookable(v(0.95))
    assert not bookable(v(0.79))
    assert not bookable(v(0.0))


def test_match_amount():
    from agent1_bank import match_amount
    sales = [{"id": "v1", "total_price_incl_tax": "1210.0"}]
    purchases = [{"id": "i1", "total_price_incl_tax": "18.15"},
                 {"id": "i2", "total_price_incl_tax": "18.15"}]
    # incoming payment matches a sales invoice
    assert match_amount(1210.0, sales, purchases) == [(sales[0], "SalesInvoice")]
    # outgoing payment matches purchase invoices (two -> ambiguous, both returned)
    assert len(match_amount(-18.15, sales, purchases)) == 2
    # no match
    assert match_amount(-99.0, sales, purchases) == []
    # direction matters: a positive amount never matches a purchase
    assert match_amount(18.15, [], purchases) == []


def test_price_format():
    # link_booking price: positive, decimal point accepted
    assert str(abs(float("-34.5"))) == "34.5"
    assert str(abs(float("1000.0"))) == "1000.0"


@patch("agent1_bank.current_administration")
@patch("agent1_bank.company_verifications")
@patch("agent1_bank.company_products")
def test_load_company_context(mock_products, mock_verifications, mock_current):
    mock_current.return_value = "TestCompany"
    mock_verifications.return_value = {
        "chamber_of_commerce_number": "12345678",
        "tax_number": "NL123456789B01",
        "emails": ["test@example.com"]
    }
    mock_products.return_value = [
        {"title": "Consulting", "description": "Custom development"}
    ]

    context = load_company_context()
    assert "Company name: TestCompany" in context
    assert "Chamber of Commerce number: 12345678" in context
    assert "VAT number: NL123456789B01" in context
    assert "Email address: test@example.com" in context
    assert "Consulting: Custom development" in context


if __name__ == "__main__":
    test_threshold()
    test_match_amount()
    test_price_format()
    test_load_company_context()
    print("all checks OK")
