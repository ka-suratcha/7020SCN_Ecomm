"""TC-1: transaction totals (ISO/IEC 25010: Functional Suitability, correctness).

Risk (report Table 1): prices and totals are stored as floating-point numbers
(FloatField), so some totals may be wrong by a very small amount.
Business rule: a customer must be charged the exact amount, to the penny.

Test design (report 3.2):
- Equivalence partitioning (EP): whole prices (10.00) and decimal prices (19.99).
- Boundary value analysis (BVA): quantity 1 (the lowest valid quantity), then 2, 3.

The checks use exact equality (==), not pytest.approx.
For money, "nearly correct" is still wrong, and approx would hide the defect.
"""

import pytest
from django.urls import reverse

from orders.models import CartInOrder, Orders


def test_tc1_1_order_total_with_whole_price(customer, address, make_product):
    """TC-1.1: the order total is price x quantity for a whole price."""
    # Arrange: a product at 10.00 (EP: whole price).
    product = make_product("Notebook", 10.00)

    # Act: create an order for 3 items.
    # Orders.save() (orders/models.py) calculates total_amount = price * quantity.
    order = Orders.objects.create(
        user=customer, address=address, product=product, quantity=3
    )

    # Assert: 10.00 x 3 = 30.00.
    assert order.total_amount == 30.00


# parametrize: run the same test once for each row of data.
# Each row is (price, quantity, expected total).
# ids: the names that pytest shows for each row in the results.
@pytest.mark.parametrize(
    ("price", "quantity", "expected"),
    [
        (19.99, 1, 19.99),  # BVA: lowest valid quantity
        (19.99, 2, 39.98),
        (19.99, 3, 59.97),
        (1.10, 3, 3.30),  # EP: decimal price; float gives 3.3000000000000003
    ],
    ids=["19.99x1", "19.99x2", "19.99x3", "1.10x3"],
)
def test_tc1_2_order_total_with_decimal_price(
    customer, address, make_product, price, quantity, expected
):
    """TC-1.2: the order total is exact for decimal prices."""
    # Arrange: a product with a decimal price (EP: decimal price).
    product = make_product("Pen", price)

    # Act: create an order. Orders.save() calculates total_amount.
    order = Orders.objects.create(
        user=customer, address=address, product=product, quantity=quantity
    )

    # Assert: the total is exact, to the penny.
    assert order.total_amount == expected


def test_tc1_3_cart_page_shows_exact_subtotal(client, make_product):
    """TC-1.3: the cart page shows the exact subtotal for two products."""
    # Arrange: two products with decimal prices.
    book = make_product("Book", 19.99)
    mug = make_product("Mug", 5.01)

    # Add 1 book and 2 mugs to the cart.
    # add_to_cart (orders/views.py) stores the cart in the session.
    # The session is the server's short-term memory for one visitor.
    # reverse("add_to_cart", args=[book.slug]) gives "/add_to_cart/book/".
    client.get(reverse("add_to_cart", args=[book.slug]))
    client.get(reverse("add_to_cart", args=[mug.slug]))
    client.get(reverse("add_to_cart", args=[mug.slug]))

    # Act: open the cart page. cart() calculates the subtotal.
    response = client.get(reverse("cart"))

    # Assert: 19.99 x 1 + 5.01 x 2 = 30.01.
    # - response.content is the HTML of the page; decode() turns it into text.
    # - We check what the customer sees, so we look for "$30.01" in the page.
    # - response.context["subtotal"] is the value the view sent to the template.
    #   The text after the comma is the message pytest shows if the check fails,
    #   so the failure is easy to read (the full HTML page is very long).
    assert response.status_code == 200
    page = response.content.decode()
    shown = response.context["subtotal"]
    assert "$30.01" in page, f"The cart page shows the subtotal as ${shown}"


def test_tc1_4_cart_order_total_adds_all_orders(customer, address, make_product):
    """TC-1.4: a cart order total is the exact sum of its orders."""
    # Arrange: two orders, as CartCheckoutView.post() creates them at checkout.
    book_order = Orders.objects.create(
        user=customer, address=address, product=make_product("Book", 19.99), quantity=1
    )
    mug_order = Orders.objects.create(
        user=customer, address=address, product=make_product("Mug", 5.01), quantity=2
    )
    cart_order = CartInOrder.objects.create(user=customer)
    cart_order.orders_in.add(book_order, mug_order)

    # Act: place() (orders/models.py) adds the total_amount of every order.
    cart_order.place()

    # Assert: 19.99 + 10.02 = 30.01.
    assert cart_order.total == 30.01
