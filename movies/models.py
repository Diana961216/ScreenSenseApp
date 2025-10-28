from django.db import models
from django.contrib.auth.models import User


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="favorites")
    tmdb_id = models.IntegerField()
    title = models.CharField(max_length=255)
    media_type = models.CharField(max_length=20)
    poster_url = models.URLField(blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.media_type}) - {self.user.username}"
