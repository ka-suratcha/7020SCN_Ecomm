"""Shared fixtures for all test files.

pytest reads conftest.py automatically.
Any test in the tests/ folder can use these fixtures by putting the name
in its brackets, for example `def test_x(customer, make_product):`.
Each test gets new objects in a new, empty test database.
"""

import pytest

from products.models import Category, Products
from shops.models import Shops
from users.models import Addresses, User


@pytest.fixture
def seller(db):
    """A seller (vendor) user.

    `db` is a pytest-django fixture that gives access to the test database.
    is_vendor=True is needed, because Shops.save() only accepts vendors.
    """
    return User.objects.create_user(
        email="seller@test.com",
        password="test-pass-123",
        username="seller",
        is_vendor=True,
    )


@pytest.fixture
def shop(seller):
    """The seller's shop. Every product must belong to a shop."""
    return Shops.objects.create(
        name="Test Shop", description="Shop for tests", user=seller
    )


@pytest.fixture
def category(seller):
    """A product category.

    The owner is set on purpose.
    The model default is owner id 1, which may not exist in the test database.
    """
    return Category.objects.create(name="Test Category", owner=seller)


@pytest.fixture
def make_product(shop, category):
    """Factory fixture: returns a function that creates a product.

    A normal fixture gives one fixed object.
    A factory fixture lets one test create many products with different prices.
    Example: make_product("Pen", 1.10) creates a product called "Pen" at 1.10.
    The name must be different for each product, because the slug
    (the name in the URL, made from the name) must be unique.
    """

    def _make_product(name, price, in_stock=10):
        return Products.objects.create(
            name=name,
            description="Product for tests",
            price=price,
            in_stock=in_stock,
            shop=shop,
            category=category,
        )

    return _make_product


@pytest.fixture
def customer(db):
    """A normal customer user (not a vendor)."""
    return User.objects.create_user(
        email="customer@test.com",
        password="test-pass-123",
        username="customer",
    )


@pytest.fixture
def address(customer):
    """A delivery address for the customer. Every order needs one."""
    return Addresses.objects.create(
        user=customer,
        full_name="Test Customer",
        phone="07000000000",
        address="1 Test Street",
        city="Coventry",
    )
