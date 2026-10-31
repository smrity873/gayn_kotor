from django.urls import path

from . import views

app_name = "swaps"

urlpatterns = [
    path("", views.swap_list, name="list"),
    path("posts/create/", views.post_create, name="post_create"),
    path("posts/<int:pk>/edit/", views.post_edit, name="post_edit"),
    path("posts/<int:pk>/deactivate/", views.post_deactivate, name="post_deactivate"),
    path("request/<int:post_id>/", views.session_request, name="session_request"),
    path("session/<int:pk>/", views.session_detail, name="session_detail"),
    path("session/<int:pk>/accept/", views.session_accept, name="session_accept"),
    path("session/<int:pk>/decline/", views.session_decline, name="session_decline"),
    path("session/<int:pk>/propose-time/", views.session_propose_time, name="session_propose_time"),
    path("session/<int:pk>/confirm/", views.session_confirm, name="session_confirm"),
    path("session/<int:pk>/set-link/", views.session_set_link, name="session_set_link"),
    path("session/<int:pk>/cancel/", views.session_cancel, name="session_cancel"),
    path("session/<int:pk>/report-outcome/", views.session_report_outcome, name="session_report_outcome"),
    path("session/<int:pk>/rate/", views.session_rate, name="session_rate"),
]
