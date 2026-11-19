from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from storages.backends.s3boto3 import S3Boto3Storage


def is_s3_url_expired(url: str, buffer_seconds: int = 3600) -> bool:
    """
    Returns True if an S3 presigned URL is expired or within buffer_seconds of expiration.
    Returns False if url is not a presigned URL or is still valid.
    """
    if not url or "X-Amz-Date=" not in url or "X-Amz-Expires=" not in url:
        return False
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        amz_date_str = params.get("X-Amz-Date", [None])[0]
        amz_expires_str = params.get("X-Amz-Expires", [None])[0]
        if not amz_date_str or not amz_expires_str:
            return False
        signed_at = datetime.strptime(amz_date_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        expires_seconds = int(amz_expires_str)
        expiration_time = signed_at + timedelta(seconds=expires_seconds)
        now = datetime.now(timezone.utc)
        return now >= (expiration_time - timedelta(seconds=buffer_seconds))
    except Exception:
        return False


class PublicMediaS3Storage(S3Boto3Storage):
    """Stores public uploaded media (e.g. course thumbnails, avatars) on S3 object storage."""
    file_overwrite = False
    default_acl = None
    querystring_auth = True
    querystring_expire = 604800  # 7 days (maximum allowed by AWS SigV4)

    def __init__(self, **settings_dict):
        settings_dict.setdefault("bucket_name", getattr(settings, "AWS_STORAGE_BUCKET_NAME", "uploads"))
        settings_dict.setdefault("endpoint_url", getattr(settings, "AWS_S3_ENDPOINT_URL", None))
        settings_dict.setdefault("region_name", getattr(settings, "AWS_S3_REGION_NAME", "ap-southeast-1"))
        settings_dict.setdefault("signature_version", getattr(settings, "AWS_S3_SIGNATURE_VERSION", "s3v4"))
        settings_dict.setdefault("location", "media")
        super().__init__(**settings_dict)


class PrivateS3Storage(S3Boto3Storage):
    """Stores protected private media (note PDFs, lesson videos) on S3 object storage."""
    file_overwrite = False
    default_acl = None
    querystring_auth = True
    querystring_expire = 604800  # 7 days (maximum allowed by AWS SigV4)

    def __init__(self, **settings_dict):
        settings_dict.setdefault("bucket_name", getattr(settings, "AWS_STORAGE_BUCKET_NAME", "uploads"))
        settings_dict.setdefault("endpoint_url", getattr(settings, "AWS_S3_ENDPOINT_URL", None))
        settings_dict.setdefault("region_name", getattr(settings, "AWS_S3_REGION_NAME", "ap-southeast-1"))
        settings_dict.setdefault("signature_version", getattr(settings, "AWS_S3_SIGNATURE_VERSION", "s3v4"))
        settings_dict.setdefault("location", "private_media")
        super().__init__(**settings_dict)


class PrivateFileSystemStorage(FileSystemStorage):
    """
    Maintains backward compatibility with existing migrations referencing PrivateFileSystemStorage.
    When USE_S3 is True, delegates file persistence to S3-compatible object storage.
    Otherwise persists to local PRIVATE_MEDIA_ROOT.
    """
    def __init__(self, location=None, base_url=None):
        self._s3_storage_instance = None
        if location is None:
            location = getattr(settings, "PRIVATE_MEDIA_ROOT", None)
        super().__init__(location=location, base_url=base_url)

    @property
    def use_s3(self):
        return getattr(settings, "USE_S3", False)

    @property
    def s3_storage(self):
        if self._s3_storage_instance is None:
            self._s3_storage_instance = PrivateS3Storage()
        return self._s3_storage_instance

    def _save(self, name, content):
        if self.use_s3:
            return self.s3_storage._save(name, content)
        return super()._save(name, content)

    def _open(self, name, mode="rb"):
        if self.use_s3:
            return self.s3_storage._open(name, mode=mode)
        return super()._open(name, mode=mode)

    def delete(self, name):
        if self.use_s3:
            return self.s3_storage.delete(name)
        return super().delete(name)

    def exists(self, name):
        if self.use_s3:
            return self.s3_storage.exists(name)
        return super().exists(name)

    def size(self, name):
        if self.use_s3:
            return self.s3_storage.size(name)
        return super().size(name)

    def url(self, name):
        if self.use_s3:
            return self.s3_storage.url(name)
        return super().url(name)

    def path(self, name):
        if self.use_s3:
            # S3 storage has no local path; raise NotImplementedError as standard
            raise NotImplementedError("This file is stored in S3 object storage and cannot be accessed via a local filesystem path.")
        return super().path(name)

    def get_valid_name(self, name):
        if self.use_s3:
            return self.s3_storage.get_valid_name(name)
        return super().get_valid_name(name)

    def get_available_name(self, name, max_length=None):
        if self.use_s3:
            return self.s3_storage.get_available_name(name, max_length=max_length)
        return super().get_available_name(name, max_length=max_length)

    def deconstruct(self):
        return ("core.storage.PrivateFileSystemStorage", [], {})


private_storage = PrivateFileSystemStorage()
