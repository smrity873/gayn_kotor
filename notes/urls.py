
from django.urls import path

from . import views

app_name = "notes"

urlpatterns = [
    path("", views.note_list, name="list"),
    path("upload/", views.upload, name="upload"),
    path("<int:pk>/preview/", views.note_preview, name="preview"),

    # Review notes
    path("reviews/", views.review_list, name="review_list"),
    path("reviews/<int:pk>/", views.review_detail, name="review_detail"),
    path("reviews/<int:pk>/action/", views.review_action, name="review_action"),
    path("<int:pk>/file/", views.note_file, name="file"),
    path('<int:pk>/', views.note_detail, name='detail'),
    path('<int:pk>/download/', views.note_download, name='download'),
    path('<int:pk>/rate/', views.note_rate, name='rate'),
]
