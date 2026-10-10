"""Window setup. The game always draws at a fixed size (e.g. 1280x720) and SDL scales it
to fit the window or the whole screen, keeping the aspect ratio (black bars if needed).
Fullscreen is borderless at the desktop resolution - no monitor mode switch - so toggling
is instant and it looks right on any TV or laptop.
"""
from __future__ import annotations

import pygame


def open_window(size: tuple[int, int], fullscreen: bool, caption: str, vsync: bool = False) -> pygame.Surface:
    """vsync is off by default: on some laptops it made every frame wait ~50 ms (18 fps);
    the game already caps itself at 60 fps."""
    pygame.display.set_caption(caption)
    flags = pygame.SCALED | pygame.RESIZABLE
    if fullscreen:
        flags |= pygame.FULLSCREEN
    if vsync:
        try:
            return pygame.display.set_mode(size, flags, vsync=1)
        except pygame.error:
            pass  # no vsync available
    return pygame.display.set_mode(size, flags)


def is_fullscreen() -> bool:
    return bool(pygame.display.get_surface().get_flags() & pygame.FULLSCREEN)


def toggle_fullscreen() -> bool:
    """Returns the new state."""
    pygame.display.toggle_fullscreen()
    return is_fullscreen()


def is_toggle_key(e) -> bool:
    """F11, or Alt+Enter."""
    return e.type == pygame.KEYDOWN and (
        e.key == pygame.K_F11 or (e.key == pygame.K_RETURN and e.mod & pygame.KMOD_ALT))
