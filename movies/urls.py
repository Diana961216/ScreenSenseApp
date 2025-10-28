from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("details/<int:item_id>/<str:media_type>/", views.details, name="details"),
    path("favorites/", views.favorites, name="favorites"),
    path(
        "add-favorite/<int:item_id>/<str:media_type>/",
        views.add_favorite,
        name="add_favorite",
    ),
    path(
        "remove-favorite/<int:fav_id>/", views.remove_favorite, name="remove_favorite"
    ),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
]
