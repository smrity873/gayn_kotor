from django.urls import path

from . import views

app_name = "credits"

urlpatterns = [
    path("hollow/", views.hollow, name="hollow"),
]