from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("details/<int:item_id>/<str:media_type>/", views.details, name="details"),
]
