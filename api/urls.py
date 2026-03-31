from django.urls import path
from api import views

urlpatterns = [
    path("", views.index),
    path("autolinks/", views.autolinks),
    path("autolinks", views.autolinks),
    path("github-repo/", views.github_repo),
    path("github-repo", views.github_repo),
    path("conversations/", views.conversations),
    path("conversations", views.conversations),
    path("conversations/<str:conversation_id>/", views.conversation_detail),
    path("conversations/<str:conversation_id>", views.conversation_detail),
]
