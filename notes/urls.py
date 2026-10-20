from django.urls import path

from . import views

app_name = "notes"

urlpatterns = [
    path("", views.note_list, name="list"),
    path("upload/", views.upload, name="upload"),
    path("<int:pk>/preview/", views.note_preview, name="preview"),
    ]