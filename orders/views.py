from django.shortcuts import render, get_object_or_404
from products import models as product_models
from users import models as user_models
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.views import View
from . import models as order_models
from orders import utiles


def ViewOrder(request, order_id):
    order = get_object_or_404(order_models.Orders, id=order_id)
    if not order.user == request.user:
        return HttpResponseRedirect("/")

    if not order.payment_method == "Cash On Delivery":
        # D-7 (Issue #12): use None when there is no Payment, so the page opens.
        # - payment_ref is empty (None) when Stripe failed on the payment page.
        # - None has no payment_id, so the old line raised AttributeError (error 500).
        # - "A if B else C" means: use A when B is true, otherwise use C.
        payment_id = order.payment_ref.payment_id if order.payment_ref else None
        # check_payment_status (orders/utiles) gives "Unpaid" for None,
        # without calling Stripe.
        payment_status = utiles.check_payment_status(payment_id)
        data = {"order": order, "payment_status": payment_status}
    else:
        data = {"order": order}

    resp = render(request, "orders/order.html", data)
    return resp


def CencelOrder(request, order_id):
    if not request.user.is_authenticated:
        return HttpResponseRedirect("/login?next=/orders/")
    order = get_object_or_404(order_models.Orders, id=order_id)
    if not order.user == request.user:
        return HttpResponseRedirect("/")

    # D-9 (Issue #15): put the stock back when an order is cancelled, only once.
    # - Before, the view only set the status, so the stock never came back.
    # - If the status is already "Cancelled", the stock came back before
    #   (here, or in payment_canceled in orders/views.py), so we skip it.
    if order.status != "Cancelled":
        # transaction.atomic(): if any step fails, every change below is undone,
        # so we never get a cancelled order without its stock back.
        with transaction.atomic():
            order.status = "Cancelled"
            order.save()
            # Put the bought quantity back into the product's stock.
            order.product.in_stock += order.quantity
            order.product.save()

    messages.success(request, "Order Cancelled Successfully", "alert-success")
    return HttpResponseRedirect("/")


def add_to_cart(request, slug):
    if "cart" not in request.session or not request.session["cart"]:
        request.session["cart"] = {"cart_count": 0}

    cart = request.session["cart"]
    if not "cart_count" in cart:
        cart["cart_count"] = 0

    if str(slug) in cart:
        cart[str(slug)]["quantity"] += 1
        cart["cart_count"] += 1
    else:
        cart[str(slug)] = {"quantity": 1}
        cart["cart_count"] += 1

    request.session.modified = True
    return HttpResponseRedirect(request.GET.get("next", "/"))


def remove_from_cart(request, slug):
    cart = request.session.get("cart", {})

    if str(slug) in cart:
        request.session["cart"]["cart_count"] -= cart[str(slug)]["quantity"]
        del cart[str(slug)]
        request.session.modified = True

    return HttpResponseRedirect(request.GET.get("next", "/"))


# remove from cart one by one
def remove_one_from_cart(request, slug):
    cart = request.session.get("cart", {})

    if str(slug) in cart:
        cart[str(slug)]["quantity"] -= 1

        if cart[str(slug)]["quantity"] == 0:
            del cart[str(slug)]

        request.session["cart"]["cart_count"] -= 1

        request.session.modified = True

    return HttpResponseRedirect(request.GET.get("next", "/"))


def cart(request):
    if "cart" not in request.session:
        return render(request, "orders/cart.html")
    products = product_models.Products.objects.filter(
        slug__in=request.session.get("cart", {}).keys()
    )
    cart_data = []

    for product in products:
        cart_data.append(
            {
                "name": product.name,
                "price": product.price,
                "slug": product.slug,
                "quantity": request.session["cart"][product.slug]["quantity"],
                "total": product.price
                * request.session["cart"][product.slug]["quantity"],
            }
        )

    subtotal = sum(
        product.price * request.session["cart"][product.slug]["quantity"]
        for product in products
    )
    return render(
        request, "orders/cart.html", {"products": cart_data, "subtotal": subtotal}
    )


def delete_address(request, address_id):
    if not request.user.is_authenticated:
        messages.info(request, "Please Login First", "alert-danger")
        return HttpResponseRedirect("/login")

    try:
        address = user_models.Addresses.objects.get(id=address_id)
    except user_models.Addresses.DoesNotExist:
        messages.info(request, "Not found", "alert-danger")
        return HttpResponseRedirect("/profile/")

    if not address.user == request.user:
        messages.info(request, "Not found", "alert-danger")
        return HttpResponseRedirect("/profile/")

    address.delete()
    messages.success(request, "Address deleted successfully", "alert-success")
    return HttpResponseRedirect("/profile/")


class CartCheckoutView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            messages.info(request, "Please Login First", "alert-danger")
            return HttpResponseRedirect("/login?next=/checkout/")

        cart_items = list(request.session.get("cart", {}).keys())
        if "cart_count" in cart_items:
            cart_items.remove("cart_count")

        savedaddress = user_models.Addresses.objects.filter(user=request.user)
        if not savedaddress:
            messages.info(request, "Add Address Before Ordering", "alert-danger")
            return HttpResponseRedirect("/save_address/?next=/checkout/")

        products = product_models.Products.objects.filter(slug__in=cart_items)
        cart_data = []

        for product in products:
            cart_data.append(
                {
                    "name": product.name,
                    "price": product.price,
                    "slug": product.slug,
                    "quantity": request.session["cart"][product.slug]["quantity"],
                    "total": product.price
                    * request.session["cart"][product.slug]["quantity"],
                }
            )

        subtotal = sum(
            product.price * request.session["cart"][product.slug]["quantity"]
            for product in products
        )
        return render(
            request,
            "orders/checkout_cart.html",
            {
                "saved_addresses": savedaddress,
                "products": cart_data,
                "subtotal": subtotal,
            },
        )

    def post(self, request):
        if not request.user.is_authenticated:
            messages.info(request, "Please Login First", "alert-danger")
            return HttpResponseRedirect("/login?next=/checkout/")

        payment_method = request.POST.get("payment_method")

        try:
            # D-11 (Issue #18): get the address only if it belongs to this user.
            # - Before, any address id was accepted, so a customer could order
            #   with another customer's address (their name, phone and home).
            # - With user=request.user, another user's address is "not found",
            #   so the except below sends the customer back to choose an address.
            savedAddresses = user_models.Addresses.objects.get(
                id=request.POST.get("savedAddresses"), user=request.user
            )
        except user_models.Addresses.DoesNotExist:
            messages.info(request, "Please Select Address", "alert-danger")
            return HttpResponseRedirect(f"/checkout/")

        # list(): read the products once, so both loops below use the same objects.
        products = list(
            product_models.Products.objects.filter(
                slug__in=request.session.get("cart", {}).keys()
            )
        )

        if not products:
            messages.info(request, "Cart is empty", "alert-danger")
            return HttpResponseRedirect(f"/")

        cart = request.session["cart"]

        # Step 1: check every item before making any order (Issue #6).
        # - One cart is one purchase: all items are ordered, or none ("all or nothing").
        # - If one item fails a check, we stop here, before anything is saved,
        #   so there is nothing to undo.
        for product in products:
            if product.shop.user == request.user:
                messages.info(request, "You can't order your own product", "alert-danger")
                return HttpResponseRedirect(f"/")

            if product.in_stock < cart[product.slug]["quantity"]:
                messages.error(request, f"Not enough stock for {product.name}", "alert-danger")
                return HttpResponseRedirect(f"/")

        # Step 2: all checks passed, so make the orders and reduce the stock.
        # transaction.atomic(): if anything fails inside this block,
        # the database undoes every change made in it (Issue #6).
        with transaction.atomic():
            inOrder = order_models.CartInOrder.objects.create(
                user=request.user,
            )

            for product in products:
                quantity = cart[product.slug]["quantity"]
                order = order_models.Orders.objects.create(
                    user=request.user,
                    address=savedAddresses,
                    payment_method=payment_method,
                    product=product,
                    quantity=quantity,
                )
                inOrder.orders_in.add(order)
                product.in_stock -= quantity
                product.save()

            inOrder.place()

        del request.session["cart"]

        if payment_method != "Cash On Delivery":
            return HttpResponseRedirect(f"/paymentCart/{inOrder.id}/")
        messages.success(request, "Order Placed Successfully", "alert-success")

        return HttpResponseRedirect("/")


class CheckoutView(View):
    def get(self, request, slug):
        if not request.user.is_authenticated:
            messages.info(request, "Please Login First", "alert-danger")
            return HttpResponseRedirect("/login?next=/checkout/")

        saved_addresses = user_models.Addresses.objects.filter(user=request.user)

        if not saved_addresses:
            messages.info(request, "Add Address Before Ordering", "alert-danger")
            return HttpResponseRedirect("/save_address/?next=/checkout/")

        product = product_models.Products.objects.get(slug=slug)
        return render(
            request,
            "orders/checkout.html",
            {"product": product, "saved_addresses": saved_addresses},
        )

    def post(self, request, slug):
        if not request.user.is_authenticated:
            messages.info(request, "Please Login First", "alert-danger")
            return HttpResponseRedirect("/login?next=/checkout/")

        try:
            product = product_models.Products.objects.get(slug=slug)
        except product_models.Products.DoesNotExist:
            return HttpResponseRedirect("/")
        
        if product.shop.user == request.user:
            messages.info(request, "You can't order your own product", "alert-danger")
            return HttpResponseRedirect("/")
        

        # Check the quantity before any order is made (Issue #5).
        # - It comes from the request, so anyone can send any value,
        #   even without the form (for example 0, -1 or "abc").
        # - int("abc") gives an error. We set qty to 0 instead,
        #   so the check below rejects it with a message.
        #   Without this, the page would crash (server error 500).
        # - Two limits: at least 1 (checked here),
        #   and not more than the stock (checked after this).
        try:
            qty = int(request.POST.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 0
        if qty < 1:
            messages.info(request, "Quantity must be at least 1", "alert-danger")
            return HttpResponseRedirect("/")

        if product.in_stock < qty:
            messages.info(request, "Not enough stock", "alert-danger")
            return HttpResponseRedirect("/")

        payment_method = request.POST.get("payment_method")

        try:
            # D-11 (Issue #18): the same check as in CartCheckoutView.post above.
            # user=request.user means only this user's own address is accepted.
            savedAddresses = user_models.Addresses.objects.get(
                id=request.POST.get("savedAddresses"), user=request.user
            )
        except user_models.Addresses.DoesNotExist:
            messages.info(request, "Please Select Address", "alert-danger")
            return HttpResponseRedirect(f"/checkout/{slug}/")

        order = order_models.Orders.objects.create(
            user=request.user,
            address=savedAddresses,
            payment_method=payment_method,
            total_amount=product.price * qty,
            product=product,
            quantity=qty,
        )
        order.save()

        product.in_stock -= qty
        product.save()


        if payment_method != "Cash On Delivery":
            return HttpResponseRedirect(f"/payment/{order.id}/")

        messages.success(request, "Order Placed Successfully", "alert-success")
        return HttpResponseRedirect("/")


def payment(request, order_id):
    if not request.user.is_authenticated:
        messages.info(request, "Please Login First", "alert-danger")
        return HttpResponseRedirect("/login")

    try:
        order = order_models.Orders.objects.get(id=order_id)
    except order_models.Orders.DoesNotExist:
        messages.info(request, "Not found", "alert-danger")
        return HttpResponseRedirect("/")

    if not order.user == request.user:
        messages.info(request, "Not found", "alert-danger")
        return HttpResponseRedirect("/")

    if order.payment_method != "Credit Card":
        return HttpResponseRedirect("/")

    payment_session = utiles.create_checkout_session(order)

    if not payment_session:
        return HttpResponseRedirect("/")

    request.session["payment_session"] = payment_session.id
    request.session.modified = True

    payment = order_models.Payment.objects.create(
        order=order, payment_id=payment_session.id
    )

    order.payment_ref = payment
    order.save()

    return HttpResponseRedirect(payment_session.url)



def paymentCart(request, CartOrder_id):

    if not request.user.is_authenticated:
        messages.info(request, "Please Login First", "alert-danger")
        return HttpResponseRedirect("/login")

    try:
        order = order_models.CartInOrder.objects.get(id=CartOrder_id)
    except order_models.CartInOrder.DoesNotExist:
        messages.info(request, "Not found", "alert-danger")
        return HttpResponseRedirect("/")

    if not order.user == request.user:
        messages.info(request, "Not found", "alert-danger")
        return HttpResponseRedirect("/")

    if order.orders_in.first().payment_method != "Credit Card":
        return HttpResponseRedirect("/")
    

    payment_session = utiles.create_checkout_session_cart(order)

    if not payment_session:
        return HttpResponseRedirect("/")

    request.session["payment_session"] = payment_session.id
    request.session.modified = True

    for order in order.orders_in.all():
        payment = order_models.Payment.objects.create(
            order=order, payment_id=payment_session.id
        )

        order.payment_ref = payment
        order.save()

    return HttpResponseRedirect(payment_session.url)

def payment_done(request):

    payment_session = request.session.get("payment_session")

    if not payment_session:
        return HttpResponseRedirect("/")

    # D-6 (Issue #11): ask Stripe if the customer really paid, before saving "paid".
    # - check_payment_status (orders/utiles) asks Stripe about this session.
    # - Stripe answers "paid" only when the money was taken.
    # - Without this check, anyone who opens /payment_done/ gets a paid order.
    if utiles.check_payment_status(payment_session) != "paid":
        # Tell the customer that the payment did not go through (red message).
        messages.info(request, "Payment not completed", "alert-danger")
        # Stop here, so the Payment stays unpaid, and go back to the home page.
        return HttpResponseRedirect("/")

    payModel = order_models.Payment.objects.filter(payment_id=payment_session)

    payModel.update(status=True)

    messages.success(request, "Order Placed Successfully", "alert-success")
    request.session["payment_session"] = None
    return HttpResponseRedirect("/")


def payment_canceled(request):
    payment_session = request.session.get("payment_session")

    if not payment_session:
        return HttpResponseRedirect("/")

    # D-8 (Issue #13): cancel the order and return its stock, then delete the Payment.
    # - Before, only the Payment was deleted. Orders.payment_ref uses
    #   on_delete=CASCADE (orders/models.py), so the order was deleted too.
    # - transaction.atomic(): if any step fails, every change below is undone,
    #   so we never get an order that is cancelled but has no stock back.
    with transaction.atomic():
        # There is normally one Payment for this Stripe session id.
        for pay in order_models.Payment.objects.filter(payment_id=payment_session):
            # The order that this Payment belongs to (Payment.order).
            order = pay.order
            # Unlink the Payment first, so deleting it no longer deletes the order.
            order.payment_ref = None
            # A cancelled payment means no purchase (design A, a stated assumption).
            order.status = "Cancelled"
            order.save()
            # Put the bought quantity back into the product's stock.
            order.product.in_stock += order.quantity
            order.product.save()
            # Now the Payment can be deleted safely.
            pay.delete()

    messages.info(request, "Payment Canceled", "alert-danger")
    request.session["payment_session"] = None
    return HttpResponseRedirect("/")
