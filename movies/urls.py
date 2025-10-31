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
    path("watchlist/", views.watchlist, name="watchlist"),
    path(
        "add-watchlist/<int:item_id>/<str:media_type>/",
        views.add_watchlist,
        name="add_watchlist",
    ),
    path(
        "remove-watchlist/<int:wl_id>/", views.remove_watchlist, name="remove_watchlist"
    ),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("suggestions/", views.suggestions, name="suggestions"),
    path("actor/<int:person_id>/<str:name>/", views.actor_search, name="actor_search"),
]
