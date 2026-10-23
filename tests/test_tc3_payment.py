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
- Payment status (report Table 2, row 3): TC-3.6 to TC-3.8 were added after a
  review found that only the "paid" case was tested. They check the other
  answers: "unpaid", no payment at all (Stripe error), and a cancelled payment.
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
    # The fake Stripe says this session is "paid".
    # - mock.patch(RETRIEVE, ...) swaps Stripe's "get this session" function
    #   for a fake one while the "with" block runs.
    # - return_value is what the fake gives back. The real Stripe gives back
    #   an object that works like a dict, so a dict is enough here.
    # - Since TC-3.6, payment_done must ask Stripe before it saves "paid",
    #   so this test needs the fake too. The expected result is the same.
    with mock.patch(RETRIEVE, return_value={"payment_status": "paid"}):
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


def card_order_with_payment(client, customer, address, make_product):
    """Make a Buy Now card order and open its payment page (with the fake Stripe).

    A helper for TC-3.6 and TC-3.8, which start from the same point.
    It is not a test or a fixture. The calling test passes its fixtures in.
    Returns the order and the product.
    """
    # Create a "Pen" at 19.99 with 10 in stock (make_product, tests/conftest.py).
    # Decimal("19.99") is exact. Without quotes, the float error stays (19.98999...).
    pen = make_product("Pen", Decimal("19.99"))

    # Log in as the customer.
    # - client: a pretend browser (pytest-django). customer: a user (conftest.py).
    # - Needed: only logged-in users can check out. Others are sent to the login
    #   page (CheckoutView.post, orders/views.py), and no order is made.
    # - Two ways: client.login(email, password) or client.force_login(user).
    #   We use force_login (no password), because this test is not about login.
    client.force_login(customer)

    # Press "Buy Now" for 1 pen, paid by card: send the form to its url.
    # - url: "checkout/<slug>/" (orders/urls.py). pen.slug fills it: /checkout/pen/
    # - What to send: each request.POST.get("...") in CheckoutView.post (views.py).
    # - quantity is not in the form, so the view uses 1. We write 1 to make it clear.
    # - CARD is "Credit Card" (top of file). address.id is the saved address number.
    # - The view saves the order and lowers stock from 10 to 9.
    client.post(
        reverse("checkout", args=[pen.slug]),
        {"quantity": 1, "payment_method": CARD, "savedAddresses": address.id},
    )

    # Read the customer's only order. get() expects exactly one row.
    order = Orders.objects.get(user=customer)

    # Open the payment page with a fake Stripe.
    # - mock.patch swaps the real function for a fake, only inside "with".
    # - CREATE (top of this file) is Stripe's "create session" function.
    # - The fake returns FAKE_SESSION (id "cs_test_123" and a url).
    # - The view saves a Payment with that id and keeps the id in the session,
    #   so payment_done and payment_cancel know which payment it is.
    with mock.patch(CREATE, return_value=FAKE_SESSION):
        client.get(reverse("payment", args=[order.id]))

    # Give both back to the calling test.
    return order, pen


def test_tc3_6_payment_done_without_payment_is_not_paid(
    client, customer, address, make_product
):
    """TC-3.6: if Stripe says "unpaid", the Payment is not marked as paid.

    Fixtures: client (pytest-django), customer, address, make_product (conftest.py).
    """
    # Arrange: make a card order and open its payment page.
    # - card_order_with_payment is the helper above. It explains each step.
    # - After it, a Payment with id "cs_test_123" exists and is not paid yet.
    # - It also returns the order and the pen. This test does not need them,
    #   so we do not keep them.
    card_order_with_payment(client, customer, address, make_product)

    # Act, part 1: put a fake Stripe "get session" in place.
    # - RETRIEVE (top of this file) is Stripe's "get this session" function.
    # - The fake answers {"payment_status": "unpaid"}, so the customer did not pay.
    # - A dict is enough, because Stripe's real answer works like a dict.
    # - Why a fake: the real Stripe needs a secret key and the internet.
    with mock.patch(RETRIEVE, return_value={"payment_status": "unpaid"}):
        # Act, part 2: open the success page without paying.
        # - "payment_done" is the url name in orders/urls.py (/payment_done/).
        # - Anyone can type this url by hand, so the test does the same.
        # - The view (payment_done, orders/views.py) should ask Stripe first.
        #   Stripe says "unpaid", so the view must not mark the payment as paid.
        client.get(reverse("payment_done"))

    # Read the Payment from the database again.
    # - payment_id is the Stripe session id that the view saved (orders/models.py).
    # - get() is safe here: the helper made exactly one Payment with this id.
    payment = Payment.objects.get(payment_id=FAKE_SESSION.id)

    # Assert: the payment must still be unpaid.
    # - status is a True or False field. True means paid (orders/models.py).
    # - "is False" checks for the exact value False.
    # - The text after the comma is the message pytest shows if the check fails.
    assert payment.status is False, "Marked as paid, but Stripe says unpaid"


def test_tc3_7_order_page_after_stripe_error_opens(
    client, customer, address, make_product
):
    """TC-3.7: if Stripe failed, the card order page still opens and shows Unpaid.

    Fixtures: client (pytest-django), customer, address, make_product (conftest.py).
    The first steps match card_order_with_payment, which explains them in full.
    """
    # Arrange: a card order, then Stripe fails when the payment page opens.
    # These are the helper's steps, except the last one,
    # so this test cannot use the helper.

    # Create a "Pen" at 19.99 with 10 in stock (make_product, conftest.py).
    pen = make_product("Pen", Decimal("19.99"))

    # Log in as the customer without a password (the helper explains why).
    client.force_login(customer)

    # Press "Buy Now" for 1 pen, paid by card (the helper explains each field).
    client.post(
        reverse("checkout", args=[pen.slug]),
        {"quantity": 1, "payment_method": CARD, "savedAddresses": address.id},
    )

    # Read the customer's only order.
    order = Orders.objects.get(user=customer)

    # Open the payment page, but make the fake Stripe raise an error.
    # - side_effect=Exception(...) means "raise this error when called".
    #   return_value would give an answer instead, as in the helper.
    # - This acts like Stripe being down, as in TC-3.3.
    # - The app catches the error, so no Payment is saved.
    #   order.payment_ref stays None (empty).
    with mock.patch(CREATE, side_effect=Exception("Stripe is not available")):
        client.get(reverse("payment", args=[order.id]))

    # Act: the customer opens the order page later.
    # - "order" is the url name in orders/urls.py (/order/<order_id>/).
    # - The view is ViewOrder (orders/views.py). For a card order it reads
    #   order.payment_ref.payment_id, so an empty payment_ref is the risk here.
    # - No fake RETRIEVE is needed. With no session id, the app should not
    #   call Stripe at all.
    # - If the view crashes, the test client raises the error on this line,
    #   so the test fails here.
    response = client.get(reverse("order", args=[order.id]))

    # Assert: 200 means the page opened normally.
    assert response.status_code == 200

    # Assert: the page says "Unpaid".
    # - response.content is the page as bytes. decode() turns it into text.
    # - "Unpaid" is what check_payment_status (orders/utiles) returns
    #   when there is no session id.
    assert "Unpaid" in response.content.decode()


def test_tc3_8_cancelled_payment_cancels_order_and_returns_stock(
    client, customer, address, make_product
):
    """TC-3.8: a payment cancelled on Stripe cancels the order and returns the stock.

    Design A (my assumption, as for D-3): a cancelled payment means no purchase,
    so the order is cancelled and the item goes back into stock.

    Fixtures: client (pytest-django), customer, address, make_product (conftest.py).
    """
    # Arrange: a card order for 1 pen, with its payment page open.
    # - The helper lowers the stock from 10 to 9 and saves a Payment.
    # - It returns two values. We keep both: order (to find it again)
    #   and pen (to check the stock).
    order, pen = card_order_with_payment(client, customer, address, make_product)

    # Act: the customer presses "cancel" on the Stripe page.
    # - Stripe then sends the browser to /payment_cancel/.
    # - "payment_cancel" is the url name in orders/urls.py.
    #   The view behind it is payment_canceled (orders/views.py).
    # - No fake Stripe is needed, because this view does not call Stripe.
    client.get(reverse("payment_cancel"))

    # Look for the order in the database again.
    # - filter(...).first() gives the order, or None if it was deleted.
    # - Not get(): if the row is gone, get() raises a long error
    #   instead of our clear message below.
    saved_order = Orders.objects.filter(id=order.id).first()

    # Read the pen again, because the view changed its stock in the database.
    # Without this, pen.in_stock still shows the old value (9) from memory.
    pen.refresh_from_db()

    # Assert: the order must still exist.
    # - The risk: Orders.payment_ref uses on_delete=CASCADE (orders/models.py),
    #   so deleting the Payment also deletes the order.
    # - The message also shows the stock, to help find the cause.
    assert saved_order is not None, f"The order was deleted. Stock is {pen.in_stock}"

    # Assert: the order is cancelled ("Cancelled" is a status in orders/models.py).
    assert saved_order.status == "Cancelled"

    # Assert: the pen is back in stock: 9 + 1 = 10.
    assert pen.in_stock == 10
