"""Abstract provider contracts.

Business logic depends ONLY on these interfaces, never on a concrete vendor.
The DI container binds a concrete implementation to each interface based on the
``*_PROVIDER`` settings, so swapping a provider is a configuration change.
"""
from app.core.interfaces.script_generator import ScriptGenerator
from app.core.interfaces.video_generator import VideoGenerator
from app.core.interfaces.voice_generator import VoiceGenerator
from app.core.interfaces.ad_platform import AdPlatform

__all__ = ["ScriptGenerator", "VideoGenerator", "VoiceGenerator", "AdPlatform"]
