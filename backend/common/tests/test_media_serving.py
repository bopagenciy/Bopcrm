import importlib
import os
import pytest
from django.conf import settings
from django.test import Client, override_settings


def test_debug_true_serves_media_file():
    """A. DEBUG=True: /media/... serves uploaded file."""
    with override_settings(DEBUG=True, ALLOWED_HOSTS=["*"]):
        import crm.urls

        importlib.reload(crm.urls)

        probe_filename = "test_media_probe.txt"
        probe_path = os.path.join(settings.MEDIA_ROOT, probe_filename)
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        with open(probe_path, "wb") as f:
            f.write(b"local media serving works")

        try:
            client = Client()
            resp = client.get(f"/media/{probe_filename}")
            assert resp.status_code == 200
            assert b"".join(resp.streaming_content) == b"local media serving works"
        finally:
            if os.path.exists(probe_path):
                os.remove(probe_path)


def test_debug_false_does_not_add_media_route():
    """B. DEBUG=False: media route is not added by crm.urls."""
    with override_settings(DEBUG=False):
        import crm.urls

        importlib.reload(crm.urls)

        has_media_pattern = any(
            getattr(p, "pattern", None) and "media" in str(p.pattern)
            for p in crm.urls.urlpatterns
        )
        assert not has_media_pattern, "Media URL pattern should not be in urlpatterns when DEBUG=False"
