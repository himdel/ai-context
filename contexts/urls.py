from django.urls import include, path, re_path
from django.views.static import serve
from django.conf import settings


def serve_with_index(request, path=""):
    doc_root = settings.STATICFILES_DIRS[0]
    full_path = doc_root / path.strip("/")
    if full_path.is_dir():
        path = path.rstrip("/") + "/index.html"
    return serve(request, path, document_root=doc_root)


urlpatterns = [
    path("api/", include("api.urls")),
    path("api", include("api.urls")),
    re_path(r"^(?P<path>.*)$", serve_with_index),
]
