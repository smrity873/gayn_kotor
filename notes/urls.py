
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

    # Appeals
    path("appeals/", views.appeals_list, name="appeals_list"),
    path("appeals/<int:pk>/action/", views.appeal_action, name="appeal_action"),

    # Flagged notes
    path("flagged/", views.flagged_list, name="flagged_list"),
    path("flagged/<int:pk>/action/", views.flagged_action, name="flagged_action"),
    path("<int:pk>/report/", views.report_note, name="report"),
    path("<int:pk>/remove/", views.remove_note_view, name="remove"),
    path("<int:pk>/appeal/", views.note_appeal, name="appeal"),
    path("<int:pk>/file/", views.note_file, name="file"),
    path('<int:pk>/', views.note_detail, name='detail'),
    path('<int:pk>/download/', views.note_download, name='download'),
    path('<int:pk>/rate/', views.note_rate, name='rate'),
]
