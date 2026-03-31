from django.urls import path
from api import views

urlpatterns = [
    path("", views.index),
    path("conversations/", views.conversations),
    path("conversations", views.conversations),
    path("conversations/<str:conversation_id>/", views.conversation_detail),
    path("conversations/<str:conversation_id>", views.conversation_detail),
]
