from django.shortcuts import render, redirect
import os, requests
from dotenv import load_dotenv
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Favorite

load_dotenv()


def home(request):
    api_key = os.getenv("TMDB_API_KEY")
    query = request.GET.get("q")
    page = int(request.GET.get("page", 1))
    results = []
    trending = []
    popular_tv = []

    next_page = None
    prev_page = None

    RESULTS_PER_PAGE = 15
    MAX_TMDB_PAGES_TO_SCAN = 10

    def fetch_tmdb_page(q, tmdb_page):
        url = "https://api.themoviedb.org/3/search/multi"
        params = {
            "api_key": api_key,
            "query": q,
            "include_adult": "false",
            "page": tmdb_page,
        }
        r = requests.get(url, params=params)
        if r.status_code != 200:
            return [], 0
        data = r.json()
        filtered = []
        for item in data.get("results", []):
            if item.get("media_type") not in ["movie", "tv"]:
                continue
            title = item.get("title") or item.get("name")
            release = item.get("release_date") or item.get("first_air_date")
            poster = item.get("poster_path")
            overview = item.get("overview")
            media_type = item.get("media_type")
            filtered.append(
                {
                    "id": item.get("id"),
                    "title": title,
                    "release": release,
                    "poster": (
                        f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
                    ),
                    "overview": overview,
                    "media_type": media_type,
                }
            )
        return filtered, data.get("total_pages", 1)

    if query:
        start = (page - 1) * RESULTS_PER_PAGE
        end = start + RESULTS_PER_PAGE

        collected = []
        seen = set()
        tmdb_page = 1
        tmdb_total_pages = 1

        while (
            len(collected) < end + 1
            and tmdb_page <= tmdb_total_pages
            and tmdb_page <= MAX_TMDB_PAGES_TO_SCAN
        ):
            page_items, tmdb_total_pages = fetch_tmdb_page(query, tmdb_page)
            for it in page_items:
                key = (it["media_type"], it["id"])
                if key in seen:
                    continue
                seen.add(key)
                collected.append(it)
                if len(collected) >= end + 1:
                    break
            tmdb_page += 1

        results = collected[start:end] if start < len(collected) else []

        prev_page = (
            page - 1
            if page > 1 and start > 0
            else (page - 1 if page > 1 and collected else None)
        )

        if len(collected) > end:
            next_page = page + 1
        else:
            next_page = None

    else:
        t_url = "https://api.themoviedb.org/3/trending/movie/week"
        p_url = "https://api.themoviedb.org/3/tv/popular"
        params = {"api_key": api_key}

        t_res = requests.get(t_url, params=params)
        if t_res.status_code == 200:
            for item in t_res.json().get("results", [])[:10]:
                trending.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "poster": (
                            f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}"
                            if item.get("poster_path")
                            else None
                        ),
                        "media_type": "movie",
                    }
                )

        p_res = requests.get(p_url, params=params)
        if p_res.status_code == 200:
            for item in p_res.json().get("results", [])[:10]:
                popular_tv.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("name"),
                        "poster": (
                            f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}"
                            if item.get("poster_path")
                            else None
                        ),
                        "media_type": "tv",
                    }
                )

    context = {
        "results": results,
        "query": query or "",
        "trending": trending,
        "popular_tv": popular_tv,
        "page": page,
        "next_page": next_page,
        "prev_page": prev_page,
    }
    return render(request, "movies/home.html", context)


def details(request, item_id, media_type):
    api_key = os.getenv("TMDB_API_KEY")
    url = f"https://api.themoviedb.org/3/{media_type}/{item_id}"
    params = {"api_key": api_key, "append_to_response": "credits,similar"}
    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()

        cast = data.get("credits", {}).get("cast", [])[:5]
        similar = data.get("similar", {}).get("results", [])[:8]

        is_favorited = False
        if request.user.is_authenticated:
            is_favorited = Favorite.objects.filter(
                user=request.user, tmdb_id=item_id, media_type=media_type
            ).exists()

        context = {
            "item": data,
            "poster": (
                f"https://image.tmdb.org/t/p/w780{data.get('poster_path')}"
                if data.get("poster_path")
                else None
            ),
            "media_type": media_type,
            "cast": cast,
            "similar": similar,
            "is_favorited": is_favorited,
        }
        return render(request, "movies/details.html", context)
    else:
        return render(request, "movies/details.html", {"error": "Details not found."})


def signup_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Account created successfully!")
            return redirect("home")
    else:
        form = UserCreationForm()
    return render(request, "movies/signup.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect("home")
    else:
        form = AuthenticationForm()
    return render(request, "movies/login.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.info(request, "You’ve been logged out.")
    return redirect("home")


@login_required
def add_favorite(request, item_id, media_type):
    api_key = os.getenv("TMDB_API_KEY")
    url = f"https://api.themoviedb.org/3/{media_type}/{item_id}"
    response = requests.get(url, params={"api_key": api_key})

    if response.status_code == 200:
        data = response.json()
        title = data.get("title") or data.get("name")
        poster_path = data.get("poster_path")
        poster_url = (
            f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
        )
        _, created = Favorite.objects.get_or_create(
            user=request.user,
            tmdb_id=item_id,
            media_type=media_type,
            defaults={"title": title, "poster_url": poster_url},
        )
        if created:
            messages.success(request, f'"{title}" added to favorites!')
        else:
            messages.info(request, f'"{title}" is already in your favorites.')
    else:
        messages.error(request, "Could not add to favorites.")

    return redirect("details", item_id=item_id, media_type=media_type)


@login_required
def favorites(request):
    user_favorites = Favorite.objects.filter(user=request.user).order_by("-added_at")
    context = {"favorites": user_favorites}
    return render(request, "movies/favorites.html", context)


@login_required
def remove_favorite(request, fav_id):
    favorite = Favorite.objects.filter(id=fav_id, user=request.user).first()
    if favorite:
        title = favorite.title
        favorite.delete()
        messages.info(request, f'"{title}" removed from favorites.')
    else:
        messages.warning(request, "Favorite not found.")
    return redirect("favorites")
