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
| TC-2 | Stock and order status after checkout | - | - | - | - | Not written yet |
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

| Status of | Values |
|---|---|
| Test | Pass, Fail, Not run yet |
| Defect | Open → Fixed (code changed) → Verified (test passes again) → Closed |
| Severity | High (wrong money, data loss, security), Medium (wrong result the user can see), Low (cosmetic) |

## 3. Test runs

I only save a log when the result changes (new tests, a defect found, or a defect fixed), not every time I run pytest.

| Run | Date | Code | What changed | Result | Log |
|---|---|---|---|---|---|
| 01 | 12 Oct 2026 | `main` (`10fa58f`) + new TC-1 tests, app code not changed | Added TC-1 | 5 passed, 3 failed | `run-01.txt` |
| 02 | 13 Oct 2026 | Branch `test/tc1-totals` + D-1 fix | Money fields changed to `DecimalField`; tests use `Decimal` | 8 passed | `run-02.txt` |

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

## 5. Defects

### D-1 Money totals are not exact

| Status | Severity | Found by | Issue | Fix | Re-test |
|---|---|---|---|---|---|
| Verified | Medium | TC-1.2 (1.10 x 3), TC-1.3, TC-1.4 in run 01 | [#3](https://github.coventry.ac.uk/kamolpanus/7020SCN_Ecomm/issues/3) | `DecimalField` + migrations `0003` | Run 02: all pass |

**What happens:** with 1 x $19.99 and 2 x $5.01 in the cart, `/cart/` shows `$30.009999999999998`, not `$30.01`.

**Is my test wrong?** No. The expected values are simple maths, the other TC-1 tests pass with the same set-up, and plain Python gives `1.10 * 3 = 3.3000000000000003` too.

**Cause:** money is stored as `FloatField` (`Products.price`, `variants.extra_price`, `Orders.total_amount`, `CartInOrder.total`). Floats cannot store values like 1.10 exactly.

**Fix:** the four fields are now `DecimalField` (2 decimal places), with migrations `products/0003` and `orders/0003`. Status becomes Closed when the PR is merged.

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
