"""Decision making: turn the game state into the next short action.

Both brains share the same features and the same safety layer, so a
comparison between them only measures the decisions themselves.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field

from jev_player.jev_client import BudgetExceeded, JevClient, JevError

YAW_FULL = 65536
TARGET_WEIGHT = {"star": 0.3, "red": 0.6, "blue": 0.7, "coin": 1.0}
GIVE_UP_SECONDS = 8.0      # stop chasing a target that we cannot reach
BLACKLIST_SECONDS = 25.0
EXPLORE_DIST = 700
ACTIONS = ("walk_to_target", "jump_to_target", "long_jump_to_target", "explore", "stop")
HOLD_FRAMES = {"walk": 0, "stop": 0, "jump": 10, "longjump": 16, "dive": 10}


def yaw_to(dx: float, dz: float) -> int:
    """SM64 yaw (0 = +Z, 16384 = +X) of the direction (dx, dz)."""
    return int(math.atan2(dx, dz) * 32768 / math.pi)


def yaw_diff(a: int, b: int) -> int:
    """Signed difference a - b wrapped to [-32768, 32767]."""
    return (a - b + 32768) % YAW_FULL - 32768


def classify_floor(dys: list[int]) -> str:
    """Floor at 150/350 units in one direction, relative to Mario's feet."""
    near, far = dys[0], dys[1]
    if near < -1500:
        return "pit" if far < -1500 else "gap"
    if near > 100:
        return "wall"
    if near < -250:
        return "drop"
    if far < -1500:
        return "pit_ahead"
    return "safe"


def probe_toward(state: dict, yaw: int) -> str:
    probes = state.get("probes") or []
    if not probes:
        return "safe"
    best = min(probes, key=lambda p: abs(yaw_diff(p["yaw"], yaw)))
    return classify_floor(best["dy"])


def bucket_distance(d: float) -> str:
    return "touching" if d < 120 else "near" if d < 400 else "medium" if d < 1200 else "far"


def bucket_height(dy: float) -> str:
    if dy > 350:
        return "far_above"
    if dy > 120:
        return "above"
    if dy < -300:
        return "below"
    return "level"


def side_of(rel: int) -> str:
    a = abs(rel)
    if a < 6000:
        return "ahead"
    if a > 26000:
        return "behind"
    return "right" if rel < 0 else "left"


@dataclass
class Decision:
    act: str          # walk | jump | longjump | stop
    tx: float
    tz: float
    reason: str
    source: str       # rule | jev | safety | cache


@dataclass
class Memory:
    """What the brains remember between ticks."""
    positions: list = field(default_factory=list)         # (time, x, z)
    target_key: tuple | None = None
    target_since: float = 0.0
    target_best_dist: float = 1e9
    blacklist: dict = field(default_factory=dict)         # key -> until time
    explore_yaw: int = 0
    last_act: str = "stop"


class Features:
    def __init__(self, state: dict, memory: Memory):
        # game time (30 frames per second) so the simulator can run faster than real time
        now = state["t"] / 30.0
        self.now = now
        self.state = state
        self.x, self.y, self.z = state["x"], state["y"], state["z"]
        self.yaw = state["yaw"]
        self.air = bool(state.get("air"))
        self.water = bool(state.get("water"))

        memory.positions.append((now, self.x, self.z))
        memory.positions[:] = [p for p in memory.positions if now - p[0] < 1.5]
        oldest = memory.positions[0]
        moved = math.hypot(self.x - oldest[1], self.z - oldest[2])
        self.stuck = (now - oldest[0] > 1.0 and moved < 60 and memory.last_act in ("walk", "jump"))

        self.target = self._pick_target(memory, now)
        if self.target:
            dx, dz = self.target["x"] - self.x, self.target["z"] - self.z
            self.dist = math.hypot(dx, dz)
            self.dy = self.target["y"] - self.y
            self.target_yaw = yaw_to(dx, dz)
            self.path = probe_toward(state, self.target_yaw)
            self._track_progress(memory, now)

    def _pick_target(self, memory: Memory, now: float):
        memory.blacklist = {k: t for k, t in memory.blacklist.items() if t > now}
        best, best_score = None, 1e18
        for obj in self.state.get("objs", []):
            key = (obj["k"], round(obj["x"] / 50), round(obj["z"] / 50))
            if key in memory.blacklist:
                continue
            d = math.dist((obj["x"], obj["y"], obj["z"]), (self.x, self.y, self.z))
            score = d * TARGET_WEIGHT.get(obj["k"], 1.0)
            if score < best_score:
                best, best_score = dict(obj, key=key), score
        return best

    def _track_progress(self, memory: Memory, now: float):
        key = self.target["key"]
        if key != memory.target_key:
            memory.target_key, memory.target_since, memory.target_best_dist = key, now, self.dist
            return
        if self.dist < memory.target_best_dist - 50:
            memory.target_best_dist, memory.target_since = self.dist, now
        elif now - memory.target_since > GIVE_UP_SECONDS:
            memory.blacklist[key] = now + BLACKLIST_SECONDS
            memory.target_key = None

    def surroundings(self) -> dict:
        out = {}
        for name, offset in (("ahead", 0), ("left", 16384), ("right", -16384), ("behind", 32768)):
            out[name] = probe_toward(self.state, (self.yaw + offset) % YAW_FULL)
        return out

    def explore_point(self, memory: Memory) -> tuple[float, float]:
        """A point ahead in a safe direction; keeps the heading until it becomes unsafe."""
        heading = memory.explore_yaw
        if self.stuck or probe_toward(self.state, heading) not in ("safe", "drop"):
            options = [(i * 8192 + heading) % YAW_FULL for i in range(1, 8)]
            safe = [y for y in options if probe_toward(self.state, y) == "safe"]
            heading = (safe or options)[0]
            memory.explore_yaw = heading
        rad = heading * math.pi / 32768
        return self.x + math.sin(rad) * EXPLORE_DIST, self.z + math.cos(rad) * EXPLORE_DIST

    def compact(self) -> dict:
        """Short, discretized description for Jev (few tokens, stable for caching)."""
        mario = {"in_air": self.air, "in_water": self.water, "stuck": self.stuck,
                 "health": self.state.get("health", 8)}
        target = None
        if self.target:
            target = {
                "kind": self.target["k"],
                "distance": bucket_distance(self.dist),
                "height": bucket_height(self.dy),
                "direction": side_of(yaw_diff(self.target_yaw, self.yaw)),
                "path": self.path,
            }
        return {"mario": mario, "target": target, "surroundings": self.surroundings()}


def to_decision(action: str, f: Features, memory: Memory, source: str, reason: str) -> Decision:
    """Map a high-level action to a concrete command and apply the safety layer."""
    if action != "explore" and action != "stop" and f.target is None:
        action = "explore"
    if action in ("walk_to_target", "jump_to_target") and f.path in ("pit", "gap") and not f.air:
        # never run into a pit; unreachable target -> look elsewhere
        memory.blacklist[f.target["key"]] = f.now + BLACKLIST_SECONDS
        action, source, reason = "explore", "safety", f"Abgrund Richtung Ziel, statt {action}"
    if action == "long_jump_to_target" and (f.path == "pit" or f.dist < 300):
        action, source, reason = "explore", "safety", "Weitsprung zu riskant"

    if action == "explore":
        tx, tz = f.explore_point(memory)
        act = "jump" if f.stuck else "walk"
    elif action == "stop":
        tx, tz, act = f.x, f.z, "stop"
    else:
        tx, tz = f.target["x"], f.target["z"]
        act = {"walk_to_target": "walk", "jump_to_target": "jump", "long_jump_to_target": "longjump"}[action]
    return Decision(act, tx, tz, reason, source)


class RuleBrain:
    name = "rule"

    def __init__(self):
        self.memory = Memory()

    def choose(self, f: Features) -> tuple[str, str]:
        if f.target is None:
            return "explore", "kein Ziel sichtbar"
        if f.water:
            return "jump_to_target", "schwimmen"
        if f.path == "gap" and f.dist > 350:
            return "long_jump_to_target", "Lücke vor dem Ziel"
        if f.stuck or f.path == "wall":
            return "jump_to_target", "Hindernis"
        if f.dy > 120 and f.dist < 500:
            return "jump_to_target", "Ziel liegt höher"
        return "walk_to_target", "Weg ist frei"

    def decide(self, state: dict) -> Decision:
        f = Features(state, self.memory)
        action, reason = self.choose(f)
        d = to_decision(action, f, self.memory, "rule", reason)
        self.memory.last_act = d.act
        return d


JEV_QUESTION = {
    "type": "choice",
    "instructions": (
        "You control Mario in Super Mario 64 and want to collect the target (coin or star). "
        "Pick Mario's next action for the next second."
    ),
    "criteria": {
        "walk_to_target": "Run to the target. Right when a target exists, its path is safe and it is not much higher than Mario.",
        "jump_to_target": "Jump toward the target. Right when the target is above Mario, a wall blocks the path, Mario is stuck or in water.",
        "long_jump_to_target": "Long jump toward the target. Right only when the path has a gap and the target is medium or far away.",
        "explore": "Run somewhere new. Right when there is no target or the path to the target is a pit.",
        "stop": "Stand still. Right only when every direction around Mario is a pit.",
    },
}


class JevBrain:
    name = "jev"

    def __init__(self, client: JevClient, min_interval: float = 0.4):
        self.client = client
        self.min_interval = min_interval
        self.memory = Memory()
        self.fallback = RuleBrain()
        self.fallback.memory = self.memory
        self._cache_key = None
        self._cache_action = None
        self._last_call = 0.0
        self.errors = 0
        self.disabled_reason = None

    def decide(self, state: dict) -> Decision:
        now = time.monotonic()
        f = Features(state, self.memory)
        compact = f.compact()
        key = json.dumps(compact, sort_keys=True)

        if self.disabled_reason:
            action, reason = self.fallback.choose(f)
            source = "rule"
        elif key == self._cache_key or now - self._last_call < self.min_interval:
            action = self._cache_action or self.fallback.choose(f)[0]
            reason, source = "gleiche Lage wie eben", "cache"
        else:
            action, reason, source = self._ask(compact, f)
            if source == "jev":
                self._cache_key, self._cache_action, self._last_call = key, action, now

        d = to_decision(action, f, self.memory, source, reason)
        self.memory.last_act = d.act
        return d

    def _ask(self, compact: dict, f: Features) -> tuple[str, str, str]:
        try:
            answers = self.client.ask(compact, {"action": JEV_QUESTION})
            answer = answers["action"]
            choice = answer["choice"]
            if choice not in ACTIONS:
                raise JevError(f"unbekannte Wahl {choice!r}")
            self.errors = 0
            return choice, f"Jev ({answer.get('confidence', 0):.0%} sicher)", "jev"
        except BudgetExceeded as error:
            self.disabled_reason = str(error)
        except (JevError, KeyError, TypeError) as error:
            self.errors += 1
            if self.errors >= 5:
                self.disabled_reason = f"5 Fehler hintereinander, zuletzt: {error}"
        action, _ = self.fallback.choose(f)
        return action, "Regel (Jev nicht verfügbar)", "rule"
