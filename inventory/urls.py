from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf", views.csrf_token),
    path("auth/login", views.login),
    path("auth/me", views.me),
    path("auth/refresh", views.refresh),
    path("auth/logout", views.logout),
    path("categories", views.categories),
    path("products", views.products),
    path("products/<int:product_id>", views.product_detail),
]
