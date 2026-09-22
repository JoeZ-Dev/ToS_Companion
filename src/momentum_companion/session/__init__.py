"""Headless application state shared by desktop and browser adapters."""

from .companion_session import CompanionSession, SessionEvent

__all__ = ["CompanionSession", "SessionEvent"]
