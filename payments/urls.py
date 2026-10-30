from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("credits/buy/", views.buy_credits, name="buy_credits"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<uuid:order_id>/", views.order_detail, name="order_detail"),
    path("sandbox/<uuid:order_id>/", views.sandbox_view, name="sandbox"),
    path("callback/", views.gateway_callback, name="callback"),
]

