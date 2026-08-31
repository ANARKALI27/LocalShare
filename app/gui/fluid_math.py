"""
Pure math for a stylized cursor-reactive "ink flow" effect — NOT a
real fluid/Navier-Stokes solver (that needs GPU shaders, which this
project's QPainter-based rendering doesn't have and was explicitly
scoped out). Instead: particles spawned at the cursor, pushed by a
cheap deterministic pseudo-curl force field (layered sine/cosine, not
true curl noise, but gives an organic non-repeating swirl without
needing a noise library), with drag and fade-out over time. Good
enough to read as "flowing ink," honest about not being physics.
"""
from __future__ import annotations

import math

MAX_PARTICLES = 160
DRAG = 0.94  # velocity multiplier per physics step — how quickly motion settles
SWIRL_STRENGTH = 55.0  # how strongly the pseudo-curl field pushes particles
MAX_LIFE = 1.6  # seconds a particle lives before fully fading out


def curl_force(x: float, y: float, t: float, scale: float = 0.01) -> tuple[float, float]:
    """
    A cheap, deterministic, smoothly-time-varying 2D force field —
    layered sine/cosine standing in for real curl noise. Not physically
    meaningful, just needs to (a) vary smoothly in space so nearby
    particles swirl together rather than independently, and (b) vary
    smoothly over time so the flow itself seems to drift rather than
    being frozen.
    """
    n1 = math.sin(x * scale + t * 0.3) + math.cos(y * scale * 1.3 - t * 0.2)
    n2 = math.sin(y * scale * 0.8 - t * 0.25) + math.cos(x * scale * 1.1 + t * 0.35)
    return (n1, n2)


def update_particle(
    x: float, y: float, vx: float, vy: float, age: float, dt: float, t: float
) -> tuple[float, float, float, float, float]:
    """One physics step for a single particle. Returns
    (new_x, new_y, new_vx, new_vy, new_age)."""
    fx, fy = curl_force(x, y, t)
    vx = vx * DRAG + fx * SWIRL_STRENGTH * dt
    vy = vy * DRAG + fy * SWIRL_STRENGTH * dt
    x = x + vx * dt
    y = y + vy * dt
    age = age + dt
    return (x, y, vx, vy, age)


def particle_alpha(age: float, max_life: float = MAX_LIFE) -> float:
    """0..1 opacity curve — quick fade-in, slower fade-out, so a fresh
    particle doesn't pop in at full brightness but does linger
    visibly before dissolving, similar to real ink dispersing."""
    if age <= 0 or age >= max_life:
        return 0.0
    progress = age / max_life
    fade_in = min(1.0, progress / 0.12)
    fade_out = max(0.0, 1.0 - progress) ** 0.6
    return max(0.0, min(1.0, fade_in * fade_out))


def is_alive(age: float, max_life: float = MAX_LIFE) -> bool:
    return 0 <= age < max_life


def spawn_velocity(cursor_vx: float, cursor_vy: float, jitter: float, seed_index: int) -> tuple[float, float]:
    """
    Initial velocity for a particle spawned at the cursor — mostly
    inherits the cursor's own movement direction/speed (so a fast
    swipe produces a fast-moving trail, a slow drift produces a gentle
    one), with a little per-particle jitter so a burst of particles
    spawned in one frame doesn't all move in an identical straight line.
    """
    angle_jitter = ((seed_index * 2654435761) % 1000 / 1000.0 - 0.5) * jitter
    cos_j, sin_j = math.cos(angle_jitter), math.sin(angle_jitter)
    vx = cursor_vx * cos_j - cursor_vy * sin_j
    vy = cursor_vx * sin_j + cursor_vy * cos_j
    return (vx, vy)
