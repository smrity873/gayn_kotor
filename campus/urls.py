from django.urls import path

from . import views

app_name = "campus"

urlpatterns = [
    path("manage/", views.manage, name="manage"),
    path("membership/<int:pk>/", views.membership_action, name="membership_action"),
]