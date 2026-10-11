"""Smoke test: the home page loads.

A simple first test.
It checks that the test set-up works before the real test cases (TC-1 to TC-6)
are added: pytest, pytest-django, the Django settings and the test database.

Type: integration test.
One request goes through urls.py, views.py, the database and the template.
"""

# pytest: the test runner. Needed for the @pytest.mark.django_db marker.
import pytest

# reverse(): gives the address of a page from its URL name.
from django.urls import reverse


# Marker(@): lets this test use the test database.
# - pytest-django creates an empty database for the test and deletes it after.
# - The real db.sqlite3 is not used.
# - Needed because home/views.py reads products and categories from the database.
# - Without it, pytest-django blocks the database query and the test fails.
@pytest.mark.django_db
def test_home_page_loads_for_a_visitor(client):
    """A visitor who is not logged in can open the home page.

    `client` is a fixture from pytest-django.
    - pytest creates it and passes it in, because its name is in the brackets.
    - It is a fake web browser. It opens pages without `runserver`.
    - It is not logged in.
    """
    # Arrange: prepare what the test needs.
    # - "home" is the URL name in home/urls.py: path("", views.home, name="home").
    # - reverse("home") turns the name into the address "/".
    # - We use the name, not "/", so the test still works if the address changes.
    url = reverse("home")

    # Act: do the one action we test.
    # - The fake browser opens "/", like typing 127.0.0.1:8000/ in a browser.
    # - `response` is what the server sends back: a status code, the HTML,
    #   and (in tests only) the list of templates used.
    response = client.get(url)

    # Assert: check the result. If a check is false, the test fails.
    # Check 1: status code 200 means OK.
    # (Other codes: 302 redirect, 404 not found, 500 server error.)
    assert response.status_code == 200

    # Check 2: it is really the home page.
    # - Status 200 alone could be another page, for example a login page.
    # - The list holds the names of all templates used to build the page.
    # - "home/index.html" is the template that home/views.py renders.
    assert "home/index.html" in [t.name for t in response.templates]
