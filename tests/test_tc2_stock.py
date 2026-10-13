"""TC-2: stock and orders after checkout (ISO/IEC 25010: Functional Suitability).

Risk (report Table 1): checkout must keep stock correct.
If stock goes wrong, the shop sells items it does not have,
or stock "grows" when nothing was returned.

Business rules tested:
- A customer can buy up to the number of items in stock, not more.
- After checkout, stock goes down by the quantity bought.
- If one item in a cart cannot be bought, nothing in that cart is ordered.
  (One cart is one purchase: all of it happens, or none of it.)

Test design (report 3.2):
- Boundary value analysis (BVA) on quantity with 5 in stock:
  1 (lowest valid), 5 (= stock, highest valid), 6 (= stock + 1, invalid).
- Equivalence partitioning (EP): invalid quantities 0 and -1.
  The checkout form does not send a quantity, but the server reads one
  from the request, so anyone can send any value. The server must check it.

Payment method is "Cash On Delivery", so no Stripe call is made (Stripe is TC-3).
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from orders.models import CartInOrder, Orders

COD = "Cash On Delivery"


def buy_now(client, product, address, quantity):
    """Send the "Buy Now" checkout form for one product (CheckoutView.post)."""
    return client.post(
        reverse("checkout", args=[product.slug]),
        {"quantity": quantity, "payment_method": COD, "savedAddresses": address.id},
    )


def test_tc2_1_buy_now_reduces_stock_and_creates_order(
    client, customer, address, make_product
):
    """TC-2.1: Buy Now creates one correct order and reduces stock."""
    # Arrange: 5 lamps in stock; the customer is logged in.
    # force_login() logs in without a password, so the test is about checkout only.
    lamp = make_product("Lamp", Decimal("12.50"), in_stock=5)
    client.force_login(customer)

    # Act: buy 2 lamps.
    buy_now(client, lamp, address, 2)

    # Assert: stock is 5 - 2 = 3, read again from the database.
    lamp.refresh_from_db()
    assert lamp.in_stock == 3
    # Assert: one order with the right data.
    order = Orders.objects.get(user=customer)
    assert order.quantity == 2
    assert order.total_amount == Decimal("25.00")
    assert order.status == "Pending"
    assert order.address == address


# Each row: quantity asked for, whether the order is accepted, stock after.
@pytest.mark.parametrize(
    ("quantity", "accepted", "stock_after"),
    [
        (1, True, 4),  # BVA: lowest valid quantity
        (5, True, 0),  # BVA: quantity = stock, highest valid
        (6, False, 5),  # BVA: quantity = stock + 1, must be rejected
    ],
    ids=["qty1", "qty5=stock", "qty6=stock+1"],
)
def test_tc2_2_buy_now_stock_boundaries(
    client, customer, address, make_product, quantity, accepted, stock_after
):
    """TC-2.2: an order up to the stock is accepted; one more is rejected."""
    # Arrange: 5 lamps in stock.
    lamp = make_product("Lamp", Decimal("12.50"), in_stock=5)
    client.force_login(customer)

    # Act
    buy_now(client, lamp, address, quantity)

    # Assert: an order exists only if it was accepted, and stock is right.
    lamp.refresh_from_db()
    assert Orders.objects.filter(user=customer).exists() == accepted
    assert lamp.in_stock == stock_after


@pytest.mark.parametrize("quantity", [0, -1, "abc"], ids=["qty0", "qty-1", "qty-abc"])
def test_tc2_3_buy_now_rejects_invalid_quantity(
    client, customer, address, make_product, quantity
):
    """TC-2.3: a quantity below 1 or not a number is rejected; stock stays."""
    # Arrange: 5 lamps in stock.
    lamp = make_product("Lamp", Decimal("12.50"), in_stock=5)
    client.force_login(customer)

    # Act: send an invalid quantity (EP: invalid partitions, below 1 and not a number).
    buy_now(client, lamp, address, quantity)

    # Assert: no order, and stock is still 5.
    # With -1, a wrong result would be stock 6 and a total of -12.50.
    # The text after the comma is the message pytest shows if the check fails.
    lamp.refresh_from_db()
    order = Orders.objects.filter(user=customer).first()
    assert order is None, (
        f"An order was created: quantity {order.quantity}, "
        f"total {order.total_amount}, stock now {lamp.in_stock}"
    )
    assert lamp.in_stock == 5


def add_to_cart(client, product, times=1):
    """Press "Add to cart" for a product the given number of times."""
    for _ in range(times):
        client.get(reverse("add_to_cart", args=[product.slug]))


def test_tc2_4_cart_checkout_orders_every_item(
    client, customer, address, make_product
):
    """TC-2.4: cart checkout orders every item, reduces stock, empties the cart."""
    # Arrange: 1 lamp and 2 mugs in the cart; 5 of each in stock.
    lamp = make_product("Lamp", Decimal("12.50"), in_stock=5)
    mug = make_product("Mug", Decimal("5.01"), in_stock=5)
    client.force_login(customer)
    add_to_cart(client, lamp)
    add_to_cart(client, mug, times=2)

    # Act: check out the whole cart (CartCheckoutView.post).
    client.post(
        reverse("cart_checkout"), {"payment_method": COD, "savedAddresses": address.id}
    )

    # Assert: stock went down by the quantity of each item.
    lamp.refresh_from_db()
    mug.refresh_from_db()
    assert lamp.in_stock == 4
    assert mug.in_stock == 3
    # Assert: one order per item, grouped in one cart order with the right total.
    assert Orders.objects.filter(user=customer).count() == 2
    cart_order = CartInOrder.objects.get(user=customer)
    assert cart_order.total == Decimal("22.52")  # 12.50 + 2 x 5.01
    # Assert: the cart is empty after checkout.
    assert "cart" not in client.session


def test_tc2_5_cart_checkout_orders_nothing_if_one_item_is_short(
    client, customer, address, make_product
):
    """TC-2.5: if one cart item is short of stock, nothing is ordered."""
    # Arrange: 1 lamp (5 in stock) and 3 mugs (only 2 in stock) in the cart.
    lamp = make_product("Lamp", Decimal("12.50"), in_stock=5)
    mug = make_product("Mug", Decimal("5.01"), in_stock=2)
    client.force_login(customer)
    add_to_cart(client, lamp)
    add_to_cart(client, mug, times=3)

    # Act: try to check out.
    client.post(
        reverse("cart_checkout"), {"payment_method": COD, "savedAddresses": address.id}
    )

    # Assert: no orders of any kind, and both stocks are unchanged.
    lamp.refresh_from_db()
    mug.refresh_from_db()
    orders = Orders.objects.filter(user=customer).count()
    cart_orders = CartInOrder.objects.filter(user=customer).count()
    assert (orders, cart_orders) == (0, 0), (
        f"{orders} order(s) and {cart_orders} cart order(s) were created; "
        f"lamp stock is {lamp.in_stock}, mug stock is {mug.in_stock}"
    )
    assert lamp.in_stock == 5
    assert mug.in_stock == 2
