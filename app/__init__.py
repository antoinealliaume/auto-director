# -*- coding: utf-8 -*-
"""Auto Director application package bootstrap.

Project-local FastAPI subclass used to attach production security and worker routes
before app.main constructs the Studio application.
"""
import fastapi as _fastapi
from .worker_status import attach as _attach_worker_status
from .local_worker_api2 import attach as _attach_local_worker_api
from .media_api import attach as _attach_media_api
from .storage_api import attach as _attach_storage_api
from .tiktok_oauth import attach as _attach_tiktok_oauth
from .tiktok_posting import attach as _attach_tiktok_posting
from .publication_api import attach as _attach_publication_api
from .security import attach as _attach_security

_BaseFastAPI = _fastapi.FastAPI


class AutoDirectorFastAPI(_BaseFastAPI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _attach_security(self)
        _attach_worker_status(self)
        _attach_local_worker_api(self)
        _attach_media_api(self)
        _attach_storage_api(self)
        _attach_tiktok_oauth(self)
        _attach_tiktok_posting(self)
        _attach_publication_api(self)


_fastapi.FastAPI = AutoDirectorFastAPI
