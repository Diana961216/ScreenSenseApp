from django.shortcuts import render
import os, requests
from dotenv import load_dotenv

load_dotenv()


def home(request):
    """Search TMDB for movies and TV shows"""
    api_key = os.getenv("TMDB_API_KEY")
    query = request.GET.get("q")

    results = []
    if query:
        url = "https://api.themoviedb.org/3/search/multi"
        params = {"api_key": api_key, "query": query, "include_adult": "false"}
        response = requests.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            for item in data.get("results", []):
                if item.get("media_type") not in ["movie", "tv"]:
                    continue
                title = item.get("title") or item.get("name")
                release = item.get("release_date") or item.get("first_air_date")
                poster = item.get("poster_path")
                overview = item.get("overview")
                media_type = item.get("media_type")

                results.append(
                    {
                        "id": item.get("id"),
                        "title": title,
                        "release": release,
                        "poster": (
                            f"https://image.tmdb.org/t/p/w500{poster}"
                            if poster
                            else None
                        ),
                        "overview": overview,
                        "media_type": media_type,
                    }
                )

    context = {"results": results, "query": query or ""}
    return render(request, "movies/home.html", context)


def details(request, item_id, media_type):
    """Display detailed info for a specific Movie or TV show"""
    api_key = os.getenv("TMDB_API_KEY")
    url = f"https://api.themoviedb.org/3/{media_type}/{item_id}"
    params = {"api_key": api_key, "append_to_response": "credits,similar"}
    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()

        # NEW: extract cast and similar lists
        cast = data.get("credits", {}).get("cast", [])[:5]
        similar = data.get("similar", {}).get("results", [])[:8]

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
        }
        return render(request, "movies/details.html", context)
    else:
        return render(request, "movies/details.html", {"error": "Details not found."})
