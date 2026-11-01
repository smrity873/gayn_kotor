"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('campus/', include('campus.urls')),
    path('credits/', include('credits.urls')),
    path('notes/', include('notes.urls')),
    path('notifications/', include('notifications.urls')),
    path('', include('core.urls')),
    path('courses/', include('courses.urls')),
    path('payments/', include('payments.urls')),
    path('swaps/', include('swaps.urls')),
]
