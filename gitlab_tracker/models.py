from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class GitLabProfile(models.Model):
    """Store GitLab token associated with a user"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='gitlab_profile')
    gitlab_token = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    gitlab_host = models.CharField(max_length=255, blank=True, null=True, default='https://gitlab.com')

    def __str__(self):
        return f"{self.user.username}'s GitLab Profile"

    @property
    def has_token(self):
        return bool(self.gitlab_token)

# MongoDB models - Using pymongo directly in service layer rather than Django ORM
