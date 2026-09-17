import io
import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status


def make_test_image(format="PNG", size=(20, 20), color="blue"):
    """Generate in-memory valid raster image file."""
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=format)
    buf.seek(0)
    ext = "jpg" if format.upper() == "JPEG" else format.lower()
    return SimpleUploadedFile(
        name=f"test_logo.{ext}",
        content=buf.getvalue(),
        content_type=f"image/{ext}",
    )


@pytest.mark.django_db
class TestOrgLogoUpload:
    """Targeted tests for Org logo upload, format/size validation, and tenant isolation."""

    url = "/api/org/settings/"

    def test_admin_upload_valid_png_success(self, admin_client, org_a):
        """A. admin uploads valid PNG -> success."""
        image_file = make_test_image("PNG")
        response = admin_client.patch(
            self.url,
            {"logo": image_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_200_OK
        org_a.refresh_from_db()
        assert org_a.logo
        assert org_a.logo.name.startswith("org_logos/")
        assert "logo_url" in response.data
        assert response.data["logo_url"] is not None

    def test_admin_upload_valid_jpeg_success(self, admin_client, org_a):
        """B. admin uploads valid JPEG -> success."""
        image_file = make_test_image("JPEG")
        response = admin_client.patch(
            self.url,
            {"logo": image_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_200_OK
        org_a.refresh_from_db()
        assert org_a.logo
        assert "test_logo" in org_a.logo.name

    def test_admin_upload_valid_webp_success(self, admin_client, org_a):
        """C. admin uploads valid WebP -> success."""
        image_file = make_test_image("WEBP")
        response = admin_client.patch(
            self.url,
            {"logo": image_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_200_OK
        org_a.refresh_from_db()
        assert org_a.logo
        assert "test_logo" in org_a.logo.name

    def test_upload_file_exceeding_2mb_rejected(self, admin_client, org_a):
        """D. file >2MB -> 400."""
        oversized_content = b"x" * (2 * 1024 * 1024 + 1)
        big_file = SimpleUploadedFile(
            name="too_big.png",
            content=oversized_content,
            content_type="image/png",
        )
        response = admin_client.patch(
            self.url,
            {"logo": big_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "logo" in response.data
        errors = str(response.data["logo"])
        assert "2 MB" in errors

    def test_upload_non_image_rejected(self, admin_client, org_a):
        """E. non-image -> 400."""
        text_file = SimpleUploadedFile(
            name="fake.png",
            content=b"This is plain text, definitely not an image.",
            content_type="image/png",
        )
        response = admin_client.patch(
            self.url,
            {"logo": text_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "logo" in response.data

    def test_upload_svg_rejected(self, admin_client, org_a):
        """F. SVG -> rejected."""
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40"/></svg>'
        svg_file = SimpleUploadedFile(
            name="vector.svg",
            content=svg_content,
            content_type="image/svg+xml",
        )
        response = admin_client.patch(
            self.url,
            {"logo": svg_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "logo" in response.data

    def test_non_admin_upload_forbidden(self, user_client, org_a, user_profile):
        """G. non-admin upload -> 403."""
        image_file = make_test_image("PNG")
        response = user_client.patch(
            self.url,
            {"logo": image_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_upload_unauthorized(self, unauthenticated_client, org_a):
        """H. unauthenticated upload -> 401/403 rejected."""
        image_file = make_test_image("PNG")
        response = unauthenticated_client.patch(
            self.url,
            {"logo": image_file},
            format="multipart",
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_tenant_isolation_cannot_alter_another_tenant(
        self, admin_client, org_a, org_b
    ):
        """I. tenant A cannot alter tenant B."""
        assert not org_b.logo

        image_file = make_test_image("PNG", color="green")
        response = admin_client.patch(
            self.url,
            {"id": str(org_b.id), "logo": image_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_200_OK

        org_a.refresh_from_db()
        assert org_a.logo

        org_b.refresh_from_db()
        assert not org_b.logo

    def test_textual_org_settings_still_update_normally(self, admin_client, org_a):
        """J. textual org settings still update normally."""
        response = admin_client.patch(
            self.url,
            {"company_name": "Acme Global Industries", "default_currency": "EUR"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        org_a.refresh_from_db()
        assert org_a.company_name == "Acme Global Industries"
        assert org_a.default_currency == "EUR"

    def test_logo_url_returned_after_upload(self, admin_client, org_a):
        """K. logo_url returned after upload."""
        image_file = make_test_image("PNG")
        response = admin_client.patch(
            self.url,
            {"logo": image_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert "logo_url" in data
        assert data["logo_url"] is not None
        assert "org_logos" in data["logo_url"]
