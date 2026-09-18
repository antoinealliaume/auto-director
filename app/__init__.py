# -*- coding: utf-8 -*-
"""Auto Director application package bootstrap.

`app.main` imports FastAPI directly. We install a tiny project-local subclass before
that import so every Studio app instance automatically exposes the same-origin worker
status route without duplicating the main application module.
"""
import fastapi as _fastapi
from .worker_status import attach as _attach_worker_status

_BaseFastAPI = _fastapi.FastAPI


class AutoDirectorFastAPI(_BaseFastAPI):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        _attach_worker_status(self)


_fastapi.FastAPI = AutoDirectorFastAPI
