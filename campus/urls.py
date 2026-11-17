from django.urls import path

from . import views

app_name = "campus"

urlpatterns = [
    path("manage/", views.manage, name="manage"),
    path("batch/<int:batch_id>/change-cr/", views.change_batch_cr, name="change_cr"),
    path("membership/<int:pk>/", views.membership_action, name="membership_action"),
]