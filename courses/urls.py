from django.urls import path
from . import views

app_name = "courses"

urlpatterns = [
    path("", views.course_list, name="course_list"),
    path("my/", views.my_courses, name="my_courses"),
    path("create/", views.course_create, name="course_create"),
    path("<int:pk>/", views.course_detail, name="course_detail"),
    path("<int:pk>/edit/", views.course_edit, name="course_edit"),
    path("<int:pk>/publish/", views.course_publish_toggle, name="course_publish_toggle"),
    path("<int:pk>/buy/", views.course_buy, name="course_buy"),
    path("<int:pk>/learn/", views.course_learn, name="course_learn"),
    path("<int:course_pk>/lessons/add/", views.lesson_create, name="lesson_create"),
    path("lessons/<int:pk>/edit/", views.lesson_edit, name="lesson_edit"),
    path("lessons/<int:pk>/delete/", views.lesson_delete, name="lesson_delete"),
    path("lesson/<int:pk>/stream/", views.lesson_stream, name="lesson_stream"),
]
