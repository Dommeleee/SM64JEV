"""A tiny stand-in for the game, used for tests and cloud experiments.

Far simpler than real SM64: flat ground, round pits, raised platforms and
coins. It produces the same state format as the Lua mod and accepts the
same commands, so the brains run unchanged.
"""

from __future__ import annotations

import math
import random

from jev_player.bridge import Command

GRAVITY = 4.0
RUN_SPEED = 28.0
NO_FLOOR = -11000


class SimWorld:
    def __init__(self, seed: int = 0, size: float = 3000, n_coins: int = 25):
        rng = random.Random(seed)
        self.size = size
        self.pits = [(rng.uniform(-size, size), rng.uniform(-size, size), rng.uniform(150, 400)) for _ in range(8)]
        self.platforms = []  # (x0, z0, x1, z1, height)
        for _ in range(6):
            x, z = rng.uniform(-size, size), rng.uniform(-size, size)
            w = rng.uniform(250, 500)
            self.platforms.append((x - w, z - w, x + w, z + w, rng.uniform(150, 230)))
        self.coins = []
        while len(self.coins) < n_coins:
            x, z = rng.uniform(-size * 0.9, size * 0.9), rng.uniform(-size * 0.9, size * 0.9)
            floor = self.floor_at(x, 1000, z)
            if floor > NO_FLOOR and not self._near_pit(x, z, 150):
                self.coins.append([x, floor + 60, z])
        self.frame = 0
        self.coins_collected = 0
        self.deaths = 0
        self.cmd = Command(-1, "stop")
        self.cmd_frame = 0
        self._respawn()

    def _near_pit(self, x, z, margin):
        return any(math.hypot(x - px, z - pz) < r + margin for px, pz, r in self.pits)

    def _respawn(self):
        self.x, self.z = 0.0, 0.0
        while self._near_pit(self.x, self.z, 200):
            self.x += 300
        self.y = self.floor_at(self.x, 1000, self.z)
        self.vy = 0.0
        self.fvel = 0.0
        self.yaw = 0
        self.air = False

    def floor_at(self, x: float, from_y: float, z: float) -> float:
        """Highest floor at (x, z) at or below from_y, like find_floor_height."""
        if abs(x) > self.size or abs(z) > self.size or self._near_pit(x, z, 0):
            return NO_FLOOR
        best = 0.0
        for x0, z0, x1, z1, h in self.platforms:
            if x0 <= x <= x1 and z0 <= z <= z1 and h <= from_y:
                best = max(best, h)
        return best if best <= from_y else NO_FLOOR

    # --- bridge interface -------------------------------------------------

    def send(self, cmd: Command) -> None:
        if cmd.id != self.cmd.id:
            self.cmd, self.cmd_frame = cmd, 0

    def read_state(self) -> dict:
        objs = sorted(self.coins, key=lambda c: math.dist(c, (self.x, self.y, self.z)))[:12]
        probes = []
        for i in range(8):
            yaw = i * 0x2000
            rad = yaw * math.pi / 0x8000
            dys = []
            for dist in (150, 350):
                fy = self.floor_at(self.x + math.sin(rad) * dist, self.y + 300, self.z + math.cos(rad) * dist)
                dys.append(round(fy - self.y))
            probes.append({"yaw": yaw, "dy": dys})
        return {
            "t": self.frame, "ack": self.cmd.id, "enabled": True, "level": 16, "area": 1,
            "x": round(self.x), "y": round(self.y), "z": round(self.z),
            "yaw": (self.yaw + 32768) % 65536 - 32768, "fvel": round(self.fvel), "vy": round(self.vy),
            "action": 0, "air": self.air, "water": False, "health": 8,
            "coins": self.coins_collected, "stars": 0, "floor_dy": 0,
            "objs": [{"k": "coin", "x": round(c[0]), "y": round(c[1]), "z": round(c[2])} for c in objs],
            "probes": probes,
        }

    # --- physics ------------------------------------------------------------

    def step(self, frames: int = 1) -> None:
        for _ in range(frames):
            self._step_once()

    def _step_once(self):
        self.frame += 1
        cmd = self.cmd
        active = cmd.id >= 0 and self.cmd_frame < cmd.frames and cmd.act != "stop"
        if active:
            dx, dz = cmd.tx - self.x, cmd.tz - self.z
            if math.hypot(dx, dz) > 5:
                self.yaw = int(math.atan2(dx, dz) * 32768 / math.pi)
            if not self.air:
                self.fvel = min(RUN_SPEED, self.fvel + 4)
                if cmd.act == "jump" and self.cmd_frame == 0:
                    self.vy, self.air = 44.0, True
                elif cmd.act == "longjump" and self.cmd_frame == 8 and self.fvel > 16:
                    self.vy, self.fvel, self.air = 30.0, 48.0, True
        elif not self.air:
            self.fvel = max(0.0, self.fvel - 6)
        self.cmd_frame += 1

        rad = self.yaw * math.pi / 32768
        nx, nz = self.x + math.sin(rad) * self.fvel, self.z + math.cos(rad) * self.fvel
        blocked = self.floor_at(nx, 1e6, nz) > self.y + 60  # a wall: higher platform
        if blocked:
            self.fvel = 0.0
        else:
            self.x, self.z = nx, nz

        floor = self.floor_at(self.x, self.y + 60, self.z)
        if self.air or self.y > floor + 1:
            self.air = True
            self.vy -= GRAVITY
            self.y += self.vy
            if self.y <= floor and floor > NO_FLOOR:
                self.y, self.vy, self.air = floor, 0.0, False
                if self.fvel > RUN_SPEED:
                    self.fvel = RUN_SPEED
        else:
            self.y = floor

        if self.y < -2000:
            self.deaths += 1
            self._respawn()

        for coin in list(self.coins):
            if math.hypot(coin[0] - self.x, coin[2] - self.z) < 100 and -80 < coin[1] - self.y < 200:
                self.coins.remove(coin)
                self.coins_collected += 1
