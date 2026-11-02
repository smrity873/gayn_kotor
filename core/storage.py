import os
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from storages.backends.s3boto3 import S3Boto3Storage


class PublicMediaS3Storage(S3Boto3Storage):
    """Stores public uploaded media (e.g. course thumbnails) on S3 object storage."""
    file_overwrite = False
    default_acl = None
    querystring_auth = False

    def __init__(self, **settings_dict):
        settings_dict.setdefault("bucket_name", getattr(settings, "AWS_STORAGE_BUCKET_NAME", "uploads"))
        settings_dict.setdefault("endpoint_url", getattr(settings, "AWS_S3_ENDPOINT_URL", None))
        settings_dict.setdefault("region_name", getattr(settings, "AWS_S3_REGION_NAME", "ap-southeast-1"))
        settings_dict.setdefault("location", "media")
        super().__init__(**settings_dict)


class PrivateS3Storage(S3Boto3Storage):
    """Stores protected private media (note PDFs, lesson videos) on S3 object storage."""
    file_overwrite = False
    default_acl = None
    querystring_auth = True
    querystring_expire = 3600

    def __init__(self, **settings_dict):
        settings_dict.setdefault("bucket_name", getattr(settings, "AWS_STORAGE_BUCKET_NAME", "uploads"))
        settings_dict.setdefault("endpoint_url", getattr(settings, "AWS_S3_ENDPOINT_URL", None))
        settings_dict.setdefault("region_name", getattr(settings, "AWS_S3_REGION_NAME", "ap-southeast-1"))
        settings_dict.setdefault("location", "private_media")
        super().__init__(**settings_dict)


class PrivateFileSystemStorage(FileSystemStorage):
    """
    Maintains backward compatibility with existing migrations referencing PrivateFileSystemStorage.
    When USE_S3 is True, delegates file persistence to S3-compatible object storage.
    Otherwise persists to local PRIVATE_MEDIA_ROOT.
    """
    def __init__(self, location=None, base_url=None):
        self._use_s3 = getattr(settings, "USE_S3", False)
        if self._use_s3:
            self._s3_storage = PrivateS3Storage()
        if location is None:
            location = getattr(settings, "PRIVATE_MEDIA_ROOT", None)
        super().__init__(location=location, base_url=base_url)

    def _save(self, name, content):
        if self._use_s3:
            return self._s3_storage._save(name, content)
        return super()._save(name, content)

    def _open(self, name, mode="rb"):
        if self._use_s3:
            return self._s3_storage._open(name, mode=mode)
        return super()._open(name, mode=mode)

    def delete(self, name):
        if self._use_s3:
            return self._s3_storage.delete(name)
        return super().delete(name)

    def exists(self, name):
        if self._use_s3:
            return self._s3_storage.exists(name)
        return super().exists(name)

    def size(self, name):
        if self._use_s3:
            return self._s3_storage.size(name)
        return super().size(name)

    def url(self, name):
        if self._use_s3:
            return self._s3_storage.url(name)
        return super().url(name)

    def path(self, name):
        if self._use_s3:
            # S3 storage has no local path; raise NotImplementedError as standard
            raise NotImplementedError("This file is stored in S3 object storage and cannot be accessed via a local filesystem path.")
        return super().path(name)

    def get_valid_name(self, name):
        if self._use_s3:
            return self._s3_storage.get_valid_name(name)
        return super().get_valid_name(name)

    def get_available_name(self, name, max_length=None):
        if self._use_s3:
            return self._s3_storage.get_available_name(name, max_length=max_length)
        return super().get_available_name(name, max_length=max_length)

    def deconstruct(self):
        return ("core.storage.PrivateFileSystemStorage", [], {})


private_storage = PrivateFileSystemStorage()
