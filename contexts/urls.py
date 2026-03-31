from django.urls import include, path, re_path
from django.views.static import serve
from django.conf import settings

urlpatterns = [
    path("api/", include("api.urls")),
    re_path(r"^(?P<path>.*)$", serve, {"document_root": settings.STATICFILES_DIRS[0]}),
]
