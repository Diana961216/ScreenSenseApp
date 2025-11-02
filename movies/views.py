from django.shortcuts import render, redirect
import os, requests
from dotenv import load_dotenv
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from collections import Counter
from .models import Favorite, Watchlist
from difflib import get_close_matches, SequenceMatcher

load_dotenv()

TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def best_name_match(search_name, candidates):
    search = search_name.lower().strip()
    search_parts = search.split()
    first_search = search_parts[0] if len(search_parts) > 0 else ""
    last_search = search_parts[-1] if len(search_parts) > 1 else ""

    best = None
    best_score = 0

    for cand in candidates:
        cand_lower = cand.lower()
        cand_parts = cand_lower.split()
        first_cand = cand_parts[0] if len(cand_parts) > 0 else ""
        last_cand = cand_parts[-1] if len(cand_parts) > 1 else ""

        first_ratio = SequenceMatcher(None, first_search, first_cand).ratio()
        last_ratio = (
            SequenceMatcher(None, last_search, last_cand).ratio()
            if last_search
            else 0.5
        )

        total_score = (first_ratio * 0.4) + (last_ratio * 0.6)
        if total_score > best_score:
            best_score = total_score
            best = cand

    if best_score >= 0.68:
        return best

    if last_search:
        for cand in candidates:
            if last_search in cand.lower():
                return cand

    for cand in candidates:
        if search in cand.lower():
            return cand

    return None


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
    search_type = request.GET.get("type", "title")
    media_filter = request.GET.get("media", "all")
    page = int(request.GET.get("page", 1))
    results = []
    trending = []
    popular_tv = []
    personalized_suggestions = []

    next_page = None
    prev_page = None
    RESULTS_PER_PAGE = 15
    MAX_TMDB_PAGES_TO_SCAN = 10

    if query and search_type == "actor":
        search_name = query.strip()
        r = requests.get(
            f"{TMDB_BASE}/search/person",
            params={
                "api_key": api_key,
                "query": search_name,
                "page": 1,
                "include_adult": "false",
            },
        )

        data = []
        if r.status_code == 200:
            data = r.json().get("results", [])

        if not data:
            simplified = "".join(
                ch for ch in search_name if ch.isalpha() or ch.isspace()
            )
            simplified = simplified.replace("nn", "n").replace("ff", "f").strip()
            second_try = requests.get(
                f"{TMDB_BASE}/search/person",
                params={
                    "api_key": api_key,
                    "query": simplified,
                    "page": 1,
                    "include_adult": "false",
                },
            )
            if second_try.status_code == 200:
                second_data = second_try.json().get("results", [])
                if second_data:
                    best = second_data[0]
                    return redirect(
                        "actor_search", person_id=best["id"], name=best["name"]
                    )

            fallback_names = []
            for page_num in range(1, 6):
                try:
                    pop = requests.get(
                        f"{TMDB_BASE}/person/popular",
                        params={"api_key": api_key, "page": page_num},
                    )
                    if pop.status_code == 200:
                        fallback_names.extend(pop.json().get("results", []))
                except Exception:
                    continue

            if fallback_names:
                names = [p.get("name", "") for p in fallback_names if p.get("name")]
                best = best_name_match(search_name, names)
                if best:
                    for p in fallback_names:
                        if p.get("name") == best:
                            return redirect(
                                "actor_search", person_id=p["id"], name=p["name"]
                            )

            search_fallback = requests.get(
                f"{TMDB_BASE}/search/person",
                params={"api_key": api_key, "query": search_name, "page": 1},
            )
            if search_fallback.status_code == 200:
                results_people = search_fallback.json().get("results", [])
                if results_people:
                    top = results_people[0]
                    return redirect(
                        "actor_search", person_id=top["id"], name=top["name"]
                    )

        if data:
            names = [p.get("name", "") for p in data if p.get("name")]
            best = best_name_match(search_name, names)
            if best:
                for p in data:
                    if p.get("name") == best:
                        return redirect(
                            "actor_search", person_id=p["id"], name=p["name"]
                        )
            first = data[0]
            if first.get("id") and first.get("name"):
                return redirect(
                    "actor_search", person_id=first["id"], name=first["name"]
                )

        messages.warning(
            request,
            f'No actor found for "{query}". Try checking spelling or shortening the name.',
        )

    if query and search_type == "genre":
        gid = None
        try:
            g_res = requests.get(
                f"{TMDB_BASE}/genre/movie/list",
                params={"api_key": api_key, "language": "en-US"},
            )
            if g_res.status_code == 200:
                for g in g_res.json().get("genres", []):
                    if g["name"].lower() == query.lower():
                        gid = g["id"]
                        break
        except Exception:
            pass

        if gid:
            d = requests.get(
                f"{TMDB_BASE}/discover/movie",
                params={"api_key": api_key, "with_genres": gid, "page": 1},
            )
            if d.status_code == 200:
                for i in d.json().get("results", [])[:20]:
                    poster = i.get("poster_path")
                    results.append(
                        {
                            "id": i.get("id"),
                            "title": i.get("title") or i.get("name"),
                            "poster": f"{IMAGE_BASE}{poster}" if poster else None,
                            "media_type": "movie",
                            "overview": i.get("overview"),
                            "release": i.get("release_date"),
                        }
                    )
        else:
            messages.warning(request, f'Genre "{query}" not found.')

        return render(
            request,
            "movies/home.html",
            {
                "results": results,
                "query": query or "",
                "search_type": search_type,
                "media": media_filter,
                "trending": [],
                "popular_tv": [],
                "personalized_suggestions": [],
                "page": page,
                "next_page": None,
                "prev_page": None,
            },
        )

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

    if query and search_type == "title":
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

        if media_filter in ("movie", "tv"):
            collected = [it for it in collected if it["media_type"] == media_filter]

        results = collected[start:end] if start < len(collected) else []
        prev_page = (
            page - 1
            if page > 1 and start > 0
            else (page - 1 if page > 1 and collected else None)
        )
        next_page = page + 1 if len(collected) > end else None

    elif not query:
        params = {"api_key": api_key}

        if media_filter in ("all", "movie"):
            t_res = requests.get(f"{TMDB_BASE}/trending/movie/week", params=params)
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

        if media_filter in ("all", "tv"):
            p_res = requests.get(f"{TMDB_BASE}/tv/popular", params=params)
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

        if (
            request.user.is_authenticated
            and Favorite.objects.filter(user=request.user).exists()
        ):
            personalized_suggestions = get_personalized_suggestions(request.user)

    context = {
        "results": results,
        "query": query or "",
        "search_type": search_type,
        "media": media_filter,
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

        watch_providers = []
        try:
            prov_res = requests.get(
                f"{TMDB_BASE}/{media_type}/{item_id}/watch/providers",
                params={"api_key": api_key},
            )
            if prov_res.status_code == 200:
                us = prov_res.json().get("results", {}).get("US", {})
                names = []
                for key in ("flatrate", "ads", "free"):
                    for entry in us.get(key, []) or []:
                        nm = entry.get("provider_name")
                        if nm and nm not in names:
                            names.append(nm)
                watch_providers = names[:10]
        except Exception:
            watch_providers = []

        is_favorited = False
        is_watchlisted = False
        if request.user.is_authenticated:
            is_favorited = Favorite.objects.filter(
                user=request.user, tmdb_id=item_id, media_type=media_type
            ).exists()
            is_watchlisted = Watchlist.objects.filter(
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
            "is_watchlisted": is_watchlisted,
            "watch_providers": watch_providers,
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
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.capitalize()}: {error}")
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
            messages.error(request, "Invalid username or password. Please try again.")
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
            if res.status_code == 200:
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

    page = request.GET.get("page", 1)
    per_page = 12
    paginator = Paginator(combined, per_page)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {"suggestions": list(page_obj.object_list), "page_obj": page_obj}
    return render(request, "movies/suggestions.html", context)


def actor_search(request, person_id, name):
    api_key = os.getenv("TMDB_API_KEY")
    credits = []
    try:
        res = requests.get(
            f"{TMDB_BASE}/person/{person_id}/combined_credits",
            params={"api_key": api_key},
        )
        if res.status_code == 200:
            data = res.json()
            for item in data.get("cast", []):
                media_type = item.get("media_type")
                if media_type not in ["movie", "tv"]:
                    continue
                poster = item.get("poster_path")
                title = item.get("title") or item.get("name")
                credits.append(
                    {
                        "id": item.get("id"),
                        "title": title,
                        "poster": f"{IMAGE_BASE}{poster}" if poster else None,
                        "media_type": media_type,
                        "release": item.get("release_date")
                        or item.get("first_air_date"),
                        "overview": item.get("overview"),
                    }
                )
    except Exception:
        pass

    def sort_key(x):
        date = x.get("release") or ""
        return (date is None, date)

    credits_sorted = sorted(credits, key=sort_key, reverse=True)

    page = request.GET.get("page", 1)
    per_page = 15
    paginator = Paginator(credits_sorted, per_page)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        "results": list(page_obj.object_list),
        "actor_name": name,
        "page_obj": page_obj,
    }
    return render(request, "movies/actor_search.html", context)


@login_required
def add_watchlist(request, item_id, media_type):
    api_key = os.getenv("TMDB_API_KEY")
    url = f"{TMDB_BASE}/{media_type}/{item_id}"
    res = requests.get(url, params={"api_key": api_key})
    if res.status_code == 200:
        data = res.json()
        title = data.get("title") or data.get("name")
        poster_path = data.get("poster_path")
        poster_url = f"{IMAGE_BASE}{poster_path}" if poster_path else None
        _, created = Watchlist.objects.get_or_create(
            user=request.user,
            tmdb_id=item_id,
            media_type=media_type,
            defaults={"title": title, "poster_url": poster_url},
        )
        if created:
            messages.success(request, f'"{title}" added to your watchlist.')
        else:
            messages.info(request, f'"{title}" is already in your watchlist.')
    else:
        messages.error(request, "Could not add to watchlist.")
    return redirect("details", item_id=item_id, media_type=media_type)


@login_required
def watchlist(request):
    items = Watchlist.objects.filter(user=request.user).order_by("-added_at")
    return render(request, "movies/watchlist.html", {"watchlist": items})


@login_required
def remove_watchlist(request, wl_id):
    item = Watchlist.objects.filter(id=wl_id, user=request.user).first()
    if item:
        title = item.title
        item.delete()
        messages.info(request, f'"{title}" removed from your watchlist.')
    else:
        messages.warning(request, "Watchlist item not found.")
    return redirect("watchlist")
