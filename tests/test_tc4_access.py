"""TC-4: access control (ISO/IEC 25010: Security, confidentiality).

Risk (report Table 2): one user sees or uses another user's data.
Ownership is checked again in each view, so one missing check is enough
to show a customer's name, address or order to someone else.

Business rules tested:
- A visitor (not logged in) is sent to the login page (TC-4.1).
- A customer cannot open or cancel another customer's order (TC-4.2).
- A customer cannot check out with another customer's saved address (TC-4.3).
- Only the shop owner can open the seller order page and the invoice (TC-4.4).

Test design (report 3.2, test plans TC-4.x.01 to TC-4.x.03):
- Each test sends the request that the wrong person could send by typing the url.
- The expected result (login page, or denied) is set before the test is run.

Payment method is "Cash On Delivery", so no Stripe call is made (Stripe is TC-3).
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from orders.models import Orders
from users.models import User

COD = "Cash On Delivery"


@pytest.fixture
def other_customer(db):
    """A second customer, who tries to use the first customer's data.

    `db` is a pytest-django fixture that gives access to the test database.
    The email and username must be different from `customer` (conftest.py),
    because both must be unique.
    """
    # create_user saves the user with a hashed password (Django's UserManager).
    return User.objects.create_user(
        email="other@test.com",
        password="test-pass-123",
        username="other",
    )


@pytest.fixture
def other_seller(db):
    """A second seller, who does not own the shop of the products in these tests.

    is_vendor=True makes this user a seller, like `seller` in conftest.py.
    """
    # Same as other_customer, but is_vendor=True.
    return User.objects.create_user(
        email="seller2@test.com",
        password="test-pass-123",
        username="seller2",
        is_vendor=True,
    )


@pytest.fixture
def order(customer, address, make_product):
    """One "Pending" order of 1 lamp by `customer`, in the shop of `seller`.

    The order is made straight in the database, so no login is needed.
    Orders.save() (orders/models.py) works out total_amount from the price.
    """
    # Make a "Lamp" with 10 in stock (make_product, conftest.py).
    lamp = make_product("Lamp", Decimal("12.50"), in_stock=10)
    # Save the order. user, product and address are required (orders/models.py).
    return Orders.objects.create(
        user=customer, product=lamp, quantity=1, address=address, payment_method=COD
    )


# Each row: the url name, and what goes into the url.
# - The url names are in orders/urls.py and seller_dashboard/urls.py.
# - "slug" means the product name in the url, "id" means the order id,
#   and None means the url has nothing to fill in.
@pytest.mark.parametrize(
    ("url_name", "fill"),
    [
        ("checkout", "slug"),  # Buy Now page (CheckoutView)
        ("cart_checkout", None),  # cart checkout page (CartCheckoutView)
        ("order", "id"),  # the customer's order page (orders ViewOrder)
        ("cancel_order", "id"),  # the customer's Cancel button (CencelOrder)
        ("dashboard", None),  # seller dashboard
        ("orders_view", None),  # seller list of orders
        ("seller_orders", "id"),  # seller order page (seller_dashboard ViewOrder)
        ("generate_invoice", "id"),  # seller invoice (PDF)
    ],
)
def test_tc4_1_visitor_is_sent_to_login(client, order, url_name, fill):
    """TC-4.1: a visitor who opens a checkout, order or seller page must log in.

    Fixtures: client (pytest-django), order (this file).
    The client is not logged in, so it acts as a visitor.
    """
    # Arrange: choose what goes into the url for this row.
    # - order.product.slug is the lamp's name in the url (products/models.py).
    # - A dict gives one value for each key, so values[fill] is this row's value.
    values = {"slug": [order.product.slug], "id": [order.id], None: []}
    # reverse() turns the url name into the url (see the urls.py files).
    url = reverse(url_name, args=values[fill])

    # Act: the visitor opens the page. response is what the server sends back.
    response = client.get(url)

    # Assert: the visitor is sent away (302 is "redirect") to the login page.
    # - response["Location"] is the address of the next page.
    # - startswith("/login") also accepts "/login?next=...".
    # - Without this, a visitor can see or change data without an account.
    assert response.status_code == 302, f"{url} opened for a visitor"
    assert response["Location"].startswith("/login"), (
        f"{url} sends a visitor to {response['Location']}, not to the login page"
    )


# Each row: the url name of a page that uses one order.
@pytest.mark.parametrize(
    "url_name",
    [
        "order",  # the order page (orders ViewOrder)
        "cancel_order",  # the Cancel button (CencelOrder)
    ],
)
def test_tc4_2_customer_cannot_use_another_customers_order(
    client, other_customer, order, url_name
):
    """TC-4.2: a customer cannot open or cancel another customer's order.

    Fixtures: client (pytest-django), other_customer and order (this file).
    """
    # Arrange: log in as the other customer (force_login, see TC-2.1).
    client.force_login(other_customer)

    # Act: open the first customer's order by typing its id in the url.
    response = client.get(reverse(url_name, args=[order.id]))

    # Read the order again, because a wrong view could change it.
    order.refresh_from_db()
    # Assert: the request is sent away (302), so the page is not shown.
    assert response.status_code == 302, "Another customer's order page opened"
    # Assert: the order did not change, so it was not cancelled by someone else.
    assert order.status == "Pending", f"Order status is now {order.status}"
    # Assert: the first customer's name is not on the page.
    # - "Test Customer" is the full_name of `address` (conftest.py).
    # - content is the page as bytes, so the name is written as bytes (b"...").
    assert b"Test Customer" not in response.content


# Each row: which checkout the other customer uses.
@pytest.mark.parametrize("checkout", ["buy_now", "cart"])
def test_tc4_3_checkout_rejects_another_customers_address(
    client, other_customer, address, make_product, checkout
):
    """TC-4.3: a customer cannot check out with another customer's saved address.

    Fixtures: client (pytest-django), other_customer (this file),
    address and make_product (conftest.py). `address` belongs to `customer`.
    """
    # Arrange: make a "Lamp" with 10 in stock (make_product, conftest.py).
    lamp = make_product("Lamp", Decimal("12.50"), in_stock=10)
    # Log in as the other customer.
    client.force_login(other_customer)

    # Act: check out, but send the id of the first customer's address.
    # - The checkout form sends the address id in "savedAddresses".
    # - Anyone can change this id in the request, so the server must check it.
    if checkout == "buy_now":
        # Buy Now for 1 lamp (CheckoutView.post, orders/views.py).
        client.post(
            reverse("checkout", args=[lamp.slug]),
            {"quantity": 1, "payment_method": COD, "savedAddresses": address.id},
        )
    else:
        # Put 1 lamp in the cart ("add_to_cart" in orders/urls.py).
        client.get(reverse("add_to_cart", args=[lamp.slug]))
        # Check out the cart (CartCheckoutView.post, orders/views.py).
        client.post(
            reverse("cart_checkout"),
            {"payment_method": COD, "savedAddresses": address.id},
        )

    # Read the lamp again, because the view may have changed its stock.
    lamp.refresh_from_db()
    # Count the orders that use the first customer's address.
    orders = Orders.objects.filter(address=address).count()
    # Assert: no order uses that address, and stock is still 10.
    # - Without this check, the order goes to someone else's home, and the
    #   other customer sees that person's name and phone on the order page.
    assert orders == 0, f"{orders} order(s) made with another customer's address"
    assert lamp.in_stock == 10


# Each row: who opens the page (a fixture name), and the url name.
@pytest.mark.parametrize(
    ("who", "url_name"),
    [
        ("other_customer", "seller_orders"),  # a customer, seller order page
        ("other_customer", "generate_invoice"),  # a customer, invoice
        ("other_seller", "seller_orders"),  # another seller, seller order page
        ("other_seller", "generate_invoice"),  # another seller, invoice
    ],
)
def test_tc4_4_only_shop_owner_opens_seller_order_pages(
    client, request, order, who, url_name
):
    """TC-4.4: only the shop owner can open a seller's order page or invoice.

    Fixtures: client and request (pytest), order (this file).
    The order is in the shop of `seller` (conftest.py), so both people are wrong.
    """
    # Arrange: log in as the person in this row.
    # - request.getfixturevalue(who) gets the fixture with that name,
    #   for example "other_seller" gives the other_seller fixture above.
    client.force_login(request.getfixturevalue(who))

    # Act: open the seller page of this order by typing its id in the url.
    response = client.get(reverse(url_name, args=[order.id]))

    # Assert: the page is not shown. 200 means "page shown".
    # - The invoice is a PDF with the customer's name, so it must not be given.
    assert response.status_code != 200, (
        f"{url_name} opened for {who}: {response['Content-Type']}"
    )
