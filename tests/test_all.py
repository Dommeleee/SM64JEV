"""Run with: python3 -m unittest discover tests"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from jev_player import jev_client
from jev_player.brains import Features, JevBrain, Memory, RuleBrain, classify_floor, to_decision
from jev_player.bridge import Command, GameBridge
from jev_player.jev_client import BudgetExceeded, JevClient
from jev_player.sim import SimWorld

REPO = Path(__file__).resolve().parent.parent
LUA = shutil.which("lua5.4") or shutil.which("lua")


def base_state(**overrides):
    state = {
        "t": 300, "x": 0, "y": 0, "z": 0, "yaw": 0, "air": False, "water": False, "health": 8,
        "coins": 0, "objs": [], "probes": [{"yaw": i * 0x2000, "dy": [0, 0]} for i in range(8)],
    }
    state.update(overrides)
    return state


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.bridge = GameBridge(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_command_file_is_public_modfs_zip(self):
        self.bridge.send(Command(7, "walk", 12.4, -30, 24))
        with zipfile.ZipFile(self.bridge.cmd_path) as zf:
            self.assertEqual(zf.read("cmd.txt").decode(), "id=7 act=walk tx=12 tz=-30 frames=24")
            props = json.loads(zf.read("properties.json"))
        self.assertTrue(props["isPublic"])
        self.assertTrue(props["files"]["cmd.txt"]["isPublic"])

    def test_reads_state_once_and_ignores_broken_file(self):
        self.bridge.sav_dir.mkdir(parents=True)
        self.bridge.state_path.write_bytes(b"half written")
        self.assertIsNone(self.bridge.read_state())
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("state.json", json.dumps(base_state()))
        self.bridge.state_path.write_bytes(buf.getvalue())
        self.assertEqual(self.bridge.read_state()["t"], 300)
        self.assertIsNone(self.bridge.read_state())  # same frame again


class BrainTest(unittest.TestCase):
    def test_floor_classes(self):
        self.assertEqual(classify_floor([0, 0]), "safe")
        self.assertEqual(classify_floor([-11000, -11000]), "pit")
        self.assertEqual(classify_floor([-11000, 0]), "gap")
        self.assertEqual(classify_floor([200, 200]), "wall")

    def test_walks_to_coin(self):
        state = base_state(objs=[{"k": "coin", "x": 0, "y": 0, "z": 800}])
        d = RuleBrain().decide(state)
        self.assertEqual((d.act, d.tx, d.tz), ("walk", 0, 800))

    def test_jumps_to_high_coin(self):
        state = base_state(objs=[{"k": "coin", "x": 0, "y": 250, "z": 300}])
        self.assertEqual(RuleBrain().decide(state).act, "jump")

    def test_safety_never_walks_into_pit(self):
        probes = [{"yaw": i * 0x2000, "dy": [-11000, -11000] if i == 0 else [0, 0]} for i in range(8)]
        state = base_state(probes=probes, objs=[{"k": "coin", "x": 0, "y": 0, "z": 900}])
        memory = Memory()
        f = Features(state, memory)
        d = to_decision("walk_to_target", f, memory, "jev", "test")
        self.assertEqual(d.source, "safety")
        self.assertNotEqual((d.tx, d.tz), (0, 900))

    def test_gives_up_unreachable_target(self):
        brain = RuleBrain()
        coin = {"k": "coin", "x": 0, "y": 0, "z": 900}
        for t in range(0, 30 * 12, 6):  # 12 s without getting closer
            brain.decide(base_state(t=t, objs=[coin]))
        self.assertEqual(len(brain.memory.blacklist), 1)


class FakeJev(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeJev.requests.append((self.headers["Authorization"], body))
        reply = {"model": "jev-test", "usage": {"input_tokens": 1000, "output_tokens": 5},
                 "answers": {"action": {"type": "choice", "choice": "jump_to_target", "confidence": 0.8,
                                        "probabilities": {}}}}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class JevClientTest(unittest.TestCase):
    def setUp(self):
        FakeJev.requests = []
        self.server = HTTPServer(("127.0.0.1", 0), FakeJev)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self.server.server_port}/v1/systemone"
        self.patch = mock.patch.object(jev_client, "API_URL", url)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.server.shutdown()

    def test_request_format_and_cost(self):
        client = JevClient("secret", budget_usd=1.0)
        answers = client.ask({"a": 1}, {"q": {"type": "noul"}})
        auth, body = FakeJev.requests[0]
        self.assertEqual(auth, "Bearer secret")
        self.assertEqual(body, {"state": {"a": 1}, "model": "jev-latest", "questions": {"q": {"type": "noul"}}})
        self.assertEqual(answers["action"]["choice"], "jump_to_target")
        self.assertAlmostEqual(client.usage.cost, 0.000042)

    def test_budget_stops_calls(self):
        client = JevClient("secret", budget_usd=0.00005)
        client.ask({}, {"q": {"type": "noul"}})
        client.ask({}, {"q": {"type": "noul"}})
        with self.assertRaises(BudgetExceeded):
            client.ask({}, {"q": {"type": "noul"}})

    def test_brain_uses_jev_then_falls_back_when_budget_is_gone(self):
        brain = JevBrain(JevClient("secret", budget_usd=0.00001), min_interval=0)
        state = base_state(objs=[{"k": "coin", "x": 0, "y": 0, "z": 800}])
        self.assertEqual(brain.decide(state).source, "jev")
        d = brain.decide(base_state(t=306, objs=[{"k": "coin", "x": 0, "y": 250, "z": 300}]))  # new situation
        self.assertEqual(d.source, "rule")
        self.assertIn("Budget", brain.disabled_reason)


class SimTest(unittest.TestCase):
    def test_rule_brain_collects_coins_without_dying(self):
        from jev_player.brains import HOLD_FRAMES
        world, brain, hold, cid = SimWorld(seed=0), RuleBrain(), -1, 0
        while world.frame < 30 * 60:
            state = world.read_state()
            if state["t"] >= hold:
                d = brain.decide(state)
                cid += 1
                world.send(Command(cid, d.act, d.tx, d.tz, 24))
                hold = state["t"] + HOLD_FRAMES[d.act]
            world.step(6)
        self.assertGreaterEqual(world.coins_collected, 8)
        self.assertEqual(world.deaths, 0)


@unittest.skipUnless(LUA, "lua5.4 not installed")
class LuaModTest(unittest.TestCase):
    def run_mod(self, cmd_line, frames):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        if cmd_line:
            (tmp / "cmd.txt").write_text(cmd_line)
        out = subprocess.run(
            [LUA, str(REPO / "tests" / "coopdx_stub.lua"), str(REPO / "mod" / "jev-mario" / "main.lua"),
             str(tmp / "state.json"), str(tmp / "cmd.txt"), "frames", str(frames)],
            capture_output=True, text=True, check=True).stdout
        state_file = tmp / "state.json"  # written every 6 frames
        return out, json.loads(state_file.read_text()) if state_file.exists() else None

    def test_state_is_valid_and_usable(self):
        out, state = self.run_mod(None, 12)
        self.assertIn("mag=0.0", out)  # no command: player keeps control
        self.assertEqual(state["objs"][0], {"k": "coin", "x": 500, "y": 60, "z": 0})
        east = [p for p in state["probes"] if p["yaw"] == 0x4000][0]
        self.assertEqual(east["dy"], [0, 0])
        self.assertEqual(RuleBrain().decide(state).act, "walk")

    def test_walk_self_calibrates_camera(self):
        out, state = self.run_mod("id=5 act=walk tx=0 tz=1000 frames=30", 12)
        self.assertIn("intendedYaw=0 ", out)  # heading +Z although camera yaw was reported wrong
        self.assertEqual(state["ack"], 5)

    def test_jump_holds_a(self):
        out, _ = self.run_mod("id=6 act=jump tx=1000 tz=0 frames=30", 4)
        self.assertIn("down=32768", out)
        self.assertIn("intendedYaw=16384", out)


if __name__ == "__main__":
    unittest.main()
