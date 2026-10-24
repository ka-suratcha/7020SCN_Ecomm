from django.db import models
from users.models import User
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, default=1)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class variants(models.Model):
    name = models.CharField(max_length=100)
    # Decimal, the same as price, because it is also money (Issue #3).
    extra_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE, default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Products(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    # Decimal, not float: money must be exact to the penny (Issue #3).
    price = models.DecimalField(max_digits=10, decimal_places=2)
    in_stock = models.IntegerField()
    variants = models.ManyToManyField(variants)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, default=1)
    shop = models.ForeignKey(
        "shops.Shops",
        on_delete=models.CASCADE,
        null=True,
        related_name="products",
        blank=True,
    )
    image = models.ImageField(upload_to="static/products/images", null=True, blank=True)
    slug = models.SlugField(unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
