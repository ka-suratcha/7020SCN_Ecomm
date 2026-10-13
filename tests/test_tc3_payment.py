"""TC-3: card payment with Stripe (ISO/IEC 25010: Functional Suitability, correctness).

Risk (report Table 1): the amount sent to Stripe is what the customer pays.
If it is wrong, the customer pays too much or too little.

Stripe is an outside service, so the tests never call it.
unittest.mock.patch puts a fake ("mock") in place of the Stripe functions:
- no internet and no real Stripe key are needed,
- no real money is taken,
- the test can still read exactly what the app sent to Stripe.

Stripe takes amounts in cents, so $19.99 must be sent as 1999.

Test design (report 3.2):
- EP: decimal prices that float cannot store exactly (19.99, 1.10, 0.29).
- Quantity 1 and 2, for Buy Now and for the cart.
- Error case: Stripe is not available.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.urls import reverse

from orders.models import CartInOrder, Orders, Payment

CARD = "Credit Card"

# The places in the app code where Stripe is called (orders/utiles/__init__.py).
CREATE = "orders.utiles.stripe.checkout.Session.create"
RETRIEVE = "orders.utiles.stripe.checkout.Session.retrieve"

# What the fake Stripe returns: a checkout session with an id and a payment page.
FAKE_SESSION = SimpleNamespace(id="cs_test_123", url="https://stripe.test/pay/123")


def charged_cents(create_mock):
    """Work out the total that the app asked Stripe to charge, in cents.

    Stripe charges unit_amount x quantity for each line item.
    """
    line_items = create_mock.call_args.kwargs["line_items"]
    return sum(i["price_data"]["unit_amount"] * i["quantity"] for i in line_items)


# Each row: price, quantity, unit amount sent (cents), total charged (cents).
@pytest.mark.parametrize(
    ("price", "quantity", "unit_cents", "total_cents"),
    [
        (Decimal("19.99"), 1, 1999, 1999),  # F-9: float gave 1998
        (Decimal("1.10"), 1, 110, 110),
        (Decimal("0.29"), 1, 29, 29),  # float: 0.29 * 100 = 28.999...
        (Decimal("19.99"), 2, 1999, 3998),
    ],
    ids=["19.99x1", "1.10x1", "0.29x1", "19.99x2"],
)
def test_tc3_1_buy_now_sends_exact_amount_to_stripe(
    client, customer, address, make_product, price, quantity, unit_cents, total_cents
):
    """TC-3.1: Buy Now by card sends the exact amount in cents to Stripe."""
    # Arrange: the customer buys by card, so checkout sends them to the payment page.
    pen = make_product("Pen", price)
    client.force_login(customer)
    client.post(
        reverse("checkout", args=[pen.slug]),
        {"quantity": quantity, "payment_method": CARD, "savedAddresses": address.id},
    )
    order = Orders.objects.get(user=customer)

    # Act: open the payment page, with the fake Stripe in place.
    with mock.patch(CREATE, return_value=FAKE_SESSION) as create:
        response = client.get(reverse("payment", args=[order.id]))

    # Assert: the amount sent to Stripe is exact.
    line_item = create.call_args.kwargs["line_items"][0]
    assert line_item["price_data"]["unit_amount"] == unit_cents
    assert charged_cents(create) == total_cents
    # Assert: the customer is sent to the Stripe payment page,
    # and a Payment record links the order to the Stripe session.
    assert response.status_code == 302
    assert response.url == FAKE_SESSION.url
    order.refresh_from_db()
    assert order.payment_ref.payment_id == FAKE_SESSION.id


def test_tc3_2_cart_payment_charges_each_item_once(
    client, customer, address, make_product
):
    """TC-3.2: cart payment by card charges the cart total, not more."""
    # Arrange: 1 lamp (12.50) and 2 mugs (5.01) in the cart; pay by card.
    lamp = make_product("Lamp", Decimal("12.50"))
    mug = make_product("Mug", Decimal("5.01"))
    client.force_login(customer)
    client.get(reverse("add_to_cart", args=[lamp.slug]))
    client.get(reverse("add_to_cart", args=[mug.slug]))
    client.get(reverse("add_to_cart", args=[mug.slug]))
    client.post(
        reverse("cart_checkout"), {"payment_method": CARD, "savedAddresses": address.id}
    )
    cart_order = CartInOrder.objects.get(user=customer)

    # Act: open the cart payment page, with the fake Stripe in place.
    with mock.patch(CREATE, return_value=FAKE_SESSION) as create:
        client.get(reverse("paymentCart", args=[cart_order.id]))

    # Assert: Stripe is asked for 12.50 + 2 x 5.01 = 22.52, so 2252 cents.
    # The text after the comma is the message pytest shows if the check fails.
    charged = charged_cents(create)
    assert charged == 2252, f"Stripe was asked to charge {charged} cents"


def test_tc3_3_stripe_error_does_not_create_payment(
    client, customer, address, make_product
):
    """TC-3.3: if Stripe fails, the customer goes back home and no Payment is saved."""
    # Arrange: a card order.
    pen = make_product("Pen", Decimal("19.99"))
    client.force_login(customer)
    client.post(
        reverse("checkout", args=[pen.slug]),
        {"quantity": 1, "payment_method": CARD, "savedAddresses": address.id},
    )
    order = Orders.objects.get(user=customer)

    # Act: the fake Stripe raises an error, like a network problem.
    with mock.patch(CREATE, side_effect=Exception("Stripe is not available")):
        response = client.get(reverse("payment", args=[order.id]))

    # Assert: the app does not crash, and no Payment record is made.
    assert response.status_code == 302
    assert response.url == "/"
    assert not Payment.objects.exists()


def test_tc3_4_payment_done_marks_payment_as_paid(
    client, customer, address, make_product
):
    """TC-3.4: after Stripe sends the customer back, the Payment is marked as paid."""
    # Arrange: a card order with a Payment record from the payment page.
    pen = make_product("Pen", Decimal("19.99"))
    client.force_login(customer)
    client.post(
        reverse("checkout", args=[pen.slug]),
        {"quantity": 1, "payment_method": CARD, "savedAddresses": address.id},
    )
    order = Orders.objects.get(user=customer)
    with mock.patch(CREATE, return_value=FAKE_SESSION):
        client.get(reverse("payment", args=[order.id]))

    # Act: Stripe sends the customer back to the success page.
    client.get(reverse("payment_done"))

    # Assert: the Payment for this Stripe session is now paid.
    assert Payment.objects.get(payment_id=FAKE_SESSION.id).status is True


def test_tc3_5_order_page_shows_card_payment_status(
    client, customer, address, make_product
):
    """TC-3.5: the customer can open the page of a card order and see its status."""
    # Arrange: a card order with a Payment record.
    pen = make_product("Pen", Decimal("19.99"))
    client.force_login(customer)
    client.post(
        reverse("checkout", args=[pen.slug]),
        {"quantity": 1, "payment_method": CARD, "savedAddresses": address.id},
    )
    order = Orders.objects.get(user=customer)
    with mock.patch(CREATE, return_value=FAKE_SESSION):
        client.get(reverse("payment", args=[order.id]))

    # Act: open the order page. ViewOrder asks Stripe for the payment status.
    # The fake Stripe answers "paid".
    with mock.patch(RETRIEVE, return_value={"payment_status": "paid"}):
        response = client.get(reverse("order", args=[order.id]))

    # Assert: the page opens and shows the status.
    assert response.status_code == 200
    assert "paid" in response.content.decode()
