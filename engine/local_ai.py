# -*- coding: utf-8 -*-
# Compatibility shim: all local AI calls now use the adaptive implementation.
from .local_ai_adaptive import enabled, refine_plan, critic_video

__all__ = ['enabled', 'refine_plan', 'critic_video']
