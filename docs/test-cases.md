# Test Cases and Defects

My record of the tests for the Ecomm fork: what I test, what happened in each run,
and the problems I found. I add to this file each time I write or run tests.

- Test code: `tests/` (fixtures in `tests/conftest.py`)
- Run logs: `docs/evidence/tests/`
- Baseline: tag `baseline-b9a2339`

## 1. Summary

| Group | What it checks | Tests | Pass | Fail | Defects | Status |
|---|---|---|---|---|---|---|
| TC-1 | Order and cart totals | 7 | 7 | 0 | D-1 (fixed) | Run 02 |
| TC-2 | Stock after checkout | 9 | 8 | 1 | D-2 (fixed), D-3 | Run 04 |
| TC-3 | Payment with Stripe (mocked) | - | - | - | - | Not written yet |
| TC-4 | Access control (who can open which page) | - | - | - | - | Not written yet |
| TC-5 | Regression (all tests again after each fix) | - | - | - | - | Not run yet |
| TC-6 | Performance (Locust) | - | - | - | - | Not run yet |

The smoke test (`tests/test_smoke.py`) only checks that pytest is set up, so it is not in this table.

## 2. How to read this file

| Word | Meaning |
|---|---|
| Test case (TC) | One check, with the result I expect. |
| Defect (D) | A real bug. A test failed, and I checked that the test itself is correct. |
| Finding (F) | Something that looks wrong (from a tool or from reading the code). No test has proved it yet. |
| Run | One time I run the whole test suite and save the log. |
| Failure vs defect | A failing test is a symptom. A defect is the cause in the code. Several failures can have one cause (one defect). |

| Status of | Values |
|---|---|
| Test | Pass, Fail, Not run yet |
| Defect | Open → Fixed (code changed) → Verified (test passes again) → Closed (Issue closed) |
| Severity | High (wrong money, data loss, security), Medium (wrong result the user can see), Low (cosmetic) |

## 3. Test runs

I only save a log when the result changes (new tests, a defect found, or a defect fixed), not every time I run pytest.

| Run | Date | Code | What changed | Result | Log |
|---|---|---|---|---|---|
| 01 | 12 Oct 2026 | `main` (`10fa58f`) + new TC-1 tests, app code not changed | Added TC-1 | 5 passed, 3 failed | `run-01.txt` |
| 02 | 13 Oct 2026 | Branch `test/tc1-totals` + D-1 fix | Money fields changed to `DecimalField`; tests use `Decimal` | 8 passed | `run-02.txt` |
| 03 | 13 Oct 2026 | Branch `test/tc2-stock`, app code not changed | Added TC-2 | 13 passed, 3 failed | `run-03.txt` |
| 04 | 13 Oct 2026 | Branch `test/tc2-stock` + D-2 fix | Quantity must be a whole number of at least 1; added TC-2.3 "abc" | 16 passed, 1 failed (TC-2.5, D-3) | `run-04.txt` |

Command (PowerShell 7): `pytest -v > docs\evidence\tests\run-NN.txt`

## 4. Test cases

### TC-1 Order and cart totals

Why: prices and totals are saved as float numbers (`FloatField`), so some totals might be a little bit wrong. A customer should always pay the exact amount.

How I chose the test data:
- Equivalence partitioning: a whole price (10.00) and decimal prices (19.99, 1.10, 5.01)
- Boundary value analysis: quantity 1 (the smallest quantity you can buy), then 2 and 3

File: `tests/test_tc1_totals.py`

| ID | Test | Data | Expected | Actual (run 01) | Run 01 | Run 02 |
|---|---|---|---|---|---|---|
| TC-1.1 | Order total, whole price | 10.00 x 3 | 30.00 | 30.0 | Pass | Pass |
| TC-1.2 | Order total, decimal price | 19.99 x 1 | 19.99 | 19.99 | Pass | Pass |
| | | 19.99 x 2 | 39.98 | 39.98 | Pass | Pass |
| | | 19.99 x 3 | 59.97 | 59.97 | Pass | Pass |
| | | 1.10 x 3 | 3.30 | 3.3000000000000003 | Fail (D-1) | Pass |
| TC-1.3 | Cart page subtotal | 1 x 19.99 + 2 x 5.01 | shows $30.01 | shows $30.009999999999998 | Fail (D-1) | Pass |
| TC-1.4 | Cart order total (`CartInOrder.place()`) | 1 x 19.99 + 2 x 5.01 | 30.01 | 30.009999999999998 | Fail (D-1) | Pass |

Notes:
- TC-1.1, 1.2 and 1.4 test the model code directly. TC-1.3 opens the cart page with the Django test client, so it tests the view and template too.
- I use exact `==` checks, because for money "almost right" is still wrong.
- Since run 02, prices are written as `Decimal("19.99")`, the type the app now uses. The expected values did not change.
- TC-1.1 and TC-1.2 read the order back from the database (`refresh_from_db()`), so they check the saved value.

### TC-2 Stock after checkout

Why: if stock goes wrong, the shop sells items it does not have, or stock grows when nothing was returned.

Rules I test:
- A customer can buy up to the number in stock, not more.
- After checkout, stock goes down by the quantity bought.
- If one item in a cart cannot be bought, nothing in that cart is ordered (**design A**, see D-3).

How I chose the test data (5 in stock):
- Boundary value analysis: quantity 1 (lowest valid), 5 (= stock), 6 (= stock + 1)
- Equivalence partitioning: invalid quantities 0 and -1, and a value that is not a number ("abc"). The form has no quantity box, but the server reads `quantity` from the request (`orders/views.py` line 274), so anyone can send any value.

All tests use "Cash On Delivery", so no Stripe call is made (Stripe is TC-3).

File: `tests/test_tc2_stock.py`

| ID | Test | Data | Expected | Actual (run 03) | Run 03 | Run 04 |
|---|---|---|---|---|---|---|
| TC-2.1 | Buy Now creates an order and reduces stock | buy 2 | stock 3; order qty 2, total 25.00, Pending | as expected | Pass | Pass |
| TC-2.2 | Buy Now stock boundaries | buy 1 | accepted, stock 4 | as expected | Pass | Pass |
| | | buy 5 | accepted, stock 0 | as expected | Pass | Pass |
| | | buy 6 | rejected, stock 5 | as expected | Pass | Pass |
| TC-2.3 | Buy Now rejects 0 or less | buy 0 | rejected, stock 5 | order with qty 0, total 0.00 | Fail (D-2) | Pass |
| | | buy -1 | rejected, stock 5 | order with qty -1, total -12.50, stock 6 | Fail (D-2) | Pass |
| | | buy "abc" | rejected, stock 5 | (added in run 04) | - | Pass |
| TC-2.4 | Cart checkout orders every item | 1 lamp + 2 mugs | 2 orders, stock 4 and 3, total 22.52, cart empty | as expected | Pass | Pass |
| TC-2.5 | Cart checkout orders nothing if one item is short | 1 lamp (5 in stock) + 3 mugs (2 in stock) | no orders, stock 5 and 2 | 1 order + 1 cart order, lamp stock 4 | Fail (D-3) | Fail (D-3) |

Notes:
- TC-2 tests use the Django test client and log in with `force_login()`, so they test the views, not only the models.
- Three tests failed, but they have two different causes in two places in the code, so they are two defects (D-2, D-3).
- The "abc" row was added with the D-2 fix, because the fix also rejects values that are not numbers, and every change needs a test. Before the fix, `int("abc")` raised an error, so the page would crash (server error 500). Normal users cannot do this, but anyone can send a request by hand.

## 5. Defects

### D-1 Money totals are not exact

| Status | Severity | Found by | Issue | Fix | Re-test |
|---|---|---|---|---|---|
| Closed | Medium | TC-1.2 (1.10 x 3), TC-1.3, TC-1.4 in run 01 | [#3](https://github.coventry.ac.uk/kamolpanus/7020SCN_Ecomm/issues/3) | `DecimalField` + migrations `0003` | Run 02: all pass |

**What happens:** with 1 x $19.99 and 2 x $5.01 in the cart, `/cart/` shows `$30.009999999999998`, not `$30.01`.

**Is my test wrong?** No. The expected values are simple maths, the other TC-1 tests pass with the same set-up, and plain Python gives `1.10 * 3 = 3.3000000000000003` too.

**Cause:** money is stored as `FloatField` (`Products.price`, `variants.extra_price`, `Orders.total_amount`, `CartInOrder.total`). Floats cannot store values like 1.10 exactly.

**Fix:** the four fields are now `DecimalField` (2 decimal places), with migrations `products/0003` and `orders/0003`. Closed when the PR was merged.

### D-2 Buy Now accepts a quantity of 0 or less

| Status | Severity | Found by | Issue | Fix | Re-test |
|---|---|---|---|---|---|
| Verified | High | TC-2.3 (0 and -1) in run 03 | [#5](https://github.coventry.ac.uk/kamolpanus/7020SCN_Ecomm/issues/5) | Quantity check in `CheckoutView.post` | Run 04: TC-2.3 passes |

**What happens:** with quantity -1, an order is made with a total of -12.50, and stock goes **up** from 5 to 6. Quantity 0 makes an empty order.

**Is my test wrong?** No. TC-2.1 and TC-2.2 pass with the same set-up, and an order of 0 or fewer items makes no sense.

**Cause:** `CheckoutView.post` (`orders/views.py` line 275) only checks that the quantity is not more than the stock. It never checks that the quantity is at least 1. Then line 299 does `in_stock -= qty`, so 5 - (-1) = 6.

**Fix:** `CheckoutView.post` now turns the quantity into a whole number, treats a value that is not a number as 0, and rejects anything below 1 with the message "Quantity must be at least 1", before any order is made.

### D-3 Cart checkout orders some items when another item is short

| Status | Severity | Found by | Issue | Fix | Re-test |
|---|---|---|---|---|---|
| Open | Medium | TC-2.5 in run 03 | [#6](https://github.coventry.ac.uk/kamolpanus/7020SCN_Ecomm/issues/6) | [commit] | [run 05] |

**What happens:** the cart has 1 lamp and 3 mugs, but only 2 mugs are in stock. The customer sees "Not enough stock", but the lamp order is already made and its stock is already 4. The cart order is not finished (`place()` is not called) and the cart is not cleared, so trying again orders the lamp a second time.

**Is my test wrong?** No. TC-2.4 (same steps, enough stock) passes.

**Cause:** `CartCheckoutView.post` (`orders/views.py` lines 204-227) makes the cart order first, then makes each order and reduces its stock inside the loop. When an item is short, it returns at once and does not undo the earlier work.

**Two possible designs** (the repository has no written requirement, so this is my assumption):
- **A. All or nothing:** check the stock of every item first; if one is short, order nothing and tell the customer.
- **B. Send what is available:** order only the items in stock, tell the customer exactly what was ordered, charge only for those, and finish the order.

The current code does neither: it orders part of the cart but tells the customer that nothing was ordered.

**Plan to fix (design A):** check the stock of every item before making any order, and wrap the checkout in `transaction.atomic`, so the database undoes everything if something fails. I chose A because the code already shows "Not enough stock" and stops (it only forgot to undo), the change is smaller, and the Stripe payment is for the whole cart.

## 6. Findings not yet confirmed

Things that look wrong but no test has proved yet. Most come from the baseline tools (`docs/evidence/baseline/`).

| ID | Where I saw it | What looks wrong | Next step |
|---|---|---|---|
| F-1 | Admin page (screenshot 04) | Names are misspelt: Orderss, Productss, Shopss, Categorys, Addressess | Low priority, fix if there is time |
| F-2 | Ruff E722 | `except:` with no error type in `seller_dashboard/views.py` line 59 hides all errors when reading the payment status | Test in TC-3 |
| F-3 | Ruff B020 | In `orders/views.py` line 375 the loop variable `order` has the same name as the list it loops over | Test in TC-3 |
| F-4 | `check --deploy` W018 | `DEBUG = True` (Debug Toolbar is visible) | Move to an environment variable |
| F-5 | Bandit B105, `check --deploy` W009 | Django `SECRET_KEY` is written in `settings.py` and is public on GitHub | Move to an environment variable |
| F-6 | Bandit B105 | `STRIPE_SECRET_KEY` is in `settings.py` (only a placeholder now) | Move with F-5 |
| F-7 | Bandit B106 | Demo passwords in `setup_dev_data.py` | OK, demo data only |
| F-8 | `check --deploy` (5 warnings) | HTTPS and cookie settings not set | Only matters for a real server |
| F-9 | Reading the code for TC-1 | `int(price * 100)` cuts off decimals, so $19.99 would be sent to Stripe as 1998 cents | The D-1 fix may also fix this (`Decimal("19.99") * 100` is 1999). Confirm in TC-3 |
| F-10 | Reading the code for TC-1 | Cart checkout sends price x quantity as the unit price and also sends the quantity, so the quantity is counted twice (2 x $10 → $40) | Test in TC-3, could be serious |
| F-11 | Writing the fixtures | `Category.owner` and `Products.category` default to id 1, which might not exist | Note only |
| F-12 | Reading `products/models.py` | Names do not follow PEP 8: the class `variants` starts with a small letter, and the field `Products.variants` has the same name as the class. Model names are plural (`Products`, `Orders`) | Not fixing: renaming models needs a migration and changes in many files, for a small gain |
