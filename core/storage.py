from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateFileSystemStorage(FileSystemStorage):
    def __init__(self, location=None, base_url=None):
        if location is None:
            location = settings.PRIVATE_MEDIA_ROOT
        super().__init__(location=location, base_url=base_url)

    def deconstruct(self):
        return ("core.storage.PrivateFileSystemStorage", [], {})


private_storage = PrivateFileSystemStorage()
