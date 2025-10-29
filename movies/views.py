from django.shortcuts import render, redirect
import os, requests
from dotenv import load_dotenv
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from collections import Counter
from .models import Favorite

load_dotenv()

TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def get_personalized_suggestions(user):
    api_key = os.getenv("TMDB_API_KEY")
    favorites = Favorite.objects.filter(user=user)
    if not favorites:
        return []

    genre_counts = Counter()
    keyword_counts = Counter()
    person_counts = Counter()

    for fav in favorites:
        try:
            details_url = f"{TMDB_BASE}/{fav.media_type}/{fav.tmdb_id}"
            details_res = requests.get(
                details_url,
                params={"api_key": api_key, "append_to_response": "credits,keywords"},
            )
            if details_res.status_code != 200:
                continue
            data = details_res.json()

            for g in data.get("genres", []):
                genre_counts[g["id"]] += 1

            keywords = data.get("keywords", {}).get("keywords") or data.get(
                "keywords", []
            )
            for k in keywords:
                keyword_counts[k["id"]] += 1

            credits = data.get("credits", {})
            for actor in credits.get("cast", [])[:5]:
                person_counts[actor["id"]] += 1
            for crew_member in credits.get("crew", []):
                if crew_member.get("job") in ["Director", "Writer", "Creator"]:
                    person_counts[crew_member["id"]] += 2
        except Exception:
            continue

    if not genre_counts and not keyword_counts and not person_counts:
        try:
            res = requests.get(
                f"{TMDB_BASE}/trending/movie/week", params={"api_key": api_key}
            )
            data = res.json().get("results", [])[:10]
            return [
                {
                    "id": item.get("id"),
                    "title": item.get("title") or item.get("name"),
                    "poster": (
                        f"{IMAGE_BASE}{item.get('poster_path')}"
                        if item.get("poster_path")
                        else None
                    ),
                    "media_type": "movie",
                }
                for item in data
                if item.get("poster_path")
            ]
        except Exception:
            return []

    top_genres = [str(gid) for gid, _ in genre_counts.most_common(3)]
    top_keywords = [str(kid) for kid, _ in keyword_counts.most_common(5)]
    top_people = [str(pid) for pid, _ in person_counts.most_common(3)]

    suggestions = []
    for media_type in ["movie", "tv"]:
        try:
            discover_url = f"{TMDB_BASE}/discover/{media_type}"
            params = {
                "api_key": api_key,
                "with_genres": ",".join(top_genres),
                "with_keywords": ",".join(top_keywords),
                "with_people": ",".join(top_people),
                "sort_by": "popularity.desc",
                "vote_count.gte": 50,
                "include_adult": "false",
                "language": "en-US",
                "page": 1,
            }
            res = requests.get(discover_url, params=params)
            if res.status_code == 200:
                for item in res.json().get("results", [])[:10]:
                    poster = item.get("poster_path")
                    if not poster:
                        continue
                    suggestions.append(
                        {
                            "id": item.get("id"),
                            "title": item.get("title") or item.get("name"),
                            "poster": f"{IMAGE_BASE}{poster}",
                            "media_type": media_type,
                        }
                    )
        except Exception:
            continue

    if not suggestions and top_genres:
        for media_type in ["movie", "tv"]:
            try:
                res = requests.get(
                    f"{TMDB_BASE}/discover/{media_type}",
                    params={
                        "api_key": api_key,
                        "with_genres": ",".join(top_genres),
                        "page": 1,
                    },
                )
                if res.status_code == 200:
                    for item in res.json().get("results", [])[:10]:
                        poster = item.get("poster_path")
                        if poster:
                            suggestions.append(
                                {
                                    "id": item.get("id"),
                                    "title": item.get("title") or item.get("name"),
                                    "poster": f"{IMAGE_BASE}{poster}",
                                    "media_type": media_type,
                                }
                            )
            except Exception:
                continue

    favorite_keys = {(f.media_type, f.tmdb_id) for f in favorites}
    seen = set()
    unique = []
    for s in suggestions:
        key = (s["media_type"], s["id"])
        if key not in seen and key not in favorite_keys:
            seen.add(key)
            unique.append(s)

    from random import shuffle

    shuffle(unique)
    return unique[:10]


def home(request):
    api_key = os.getenv("TMDB_API_KEY")
    query = request.GET.get("q")
    page = int(request.GET.get("page", 1))
    results = []
    trending = []
    popular_tv = []
    personalized_suggestions = []

    next_page = None
    prev_page = None
    RESULTS_PER_PAGE = 15
    MAX_TMDB_PAGES_TO_SCAN = 10

    def fetch_tmdb_page(q, tmdb_page):
        url = f"{TMDB_BASE}/search/multi"
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
                    "poster": f"{IMAGE_BASE}{poster}" if poster else None,
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
        next_page = page + 1 if len(collected) > end else None

    else:
        t_url = f"{TMDB_BASE}/trending/movie/week"
        p_url = f"{TMDB_BASE}/tv/popular"
        params = {"api_key": api_key}

        t_res = requests.get(t_url, params=params)
        if t_res.status_code == 200:
            for item in t_res.json().get("results", [])[:10]:
                trending.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "poster": (
                            f"{IMAGE_BASE}{item.get('poster_path')}"
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
                            f"{IMAGE_BASE}{item.get('poster_path')}"
                            if item.get("poster_path")
                            else None
                        ),
                        "media_type": "tv",
                    }
                )

        # Personalized suggestions for logged-in users with favorites
        if (
            request.user.is_authenticated
            and Favorite.objects.filter(user=request.user).exists()
        ):
            personalized_suggestions = get_personalized_suggestions(request.user)

    context = {
        "results": results,
        "query": query or "",
        "trending": trending,
        "popular_tv": popular_tv,
        "personalized_suggestions": personalized_suggestions,
        "page": page,
        "next_page": next_page,
        "prev_page": prev_page,
    }
    return render(request, "movies/home.html", context)


def details(request, item_id, media_type):
    api_key = os.getenv("TMDB_API_KEY")
    url = f"{TMDB_BASE}/{media_type}/{item_id}"
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
    url = f"{TMDB_BASE}/{media_type}/{item_id}"
    response = requests.get(url, params={"api_key": api_key})

    if response.status_code == 200:
        data = response.json()
        title = data.get("title") or data.get("name")
        poster_path = data.get("poster_path")
        poster_url = f"{IMAGE_BASE}{poster_path}" if poster_path else None
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


@login_required
def suggestions(request):
    api_key = os.getenv("TMDB_API_KEY")

    base = get_personalized_suggestions(request.user)

    more = []
    user_favs = Favorite.objects.filter(user=request.user).order_by("-added_at")[:6]

    for fav in user_favs:
        try:
            rec_url = f"{TMDB_BASE}/{fav.media_type}/{fav.tmdb_id}/recommendations"
            res = requests.get(rec_url, params={"api_key": api_key, "page": 1})
            if res.status_code != 200:
                continue
            for item in res.json().get("results", [])[:10]:
                poster = item.get("poster_path")
                if not poster:
                    continue
                more.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title") or item.get("name"),
                        "poster": f"{IMAGE_BASE}{poster}",
                        "media_type": (
                            fav.media_type
                            if item.get("media_type") is None
                            else item.get("media_type")
                        ),
                    }
                )
        except Exception:
            continue

    favorite_keys = {
        (f.media_type, f.tmdb_id) for f in Favorite.objects.filter(user=request.user)
    }
    seen = {(x["media_type"], x["id"]) for x in base}
    combined = base[:]
    for s in more:
        key = (s["media_type"], s["id"])
        if key not in seen and key not in favorite_keys:
            seen.add(key)
            combined.append(s)

    combined = combined[:40]

    context = {
        "suggestions": combined,
    }
    return render(request, "movies/suggestions.html", context)
