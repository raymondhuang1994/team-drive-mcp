"""Deterministic lifecycle races without launching services or touching sources."""
import contextlib
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from team_drive.broker import Broker
from team_drive.bridge import Bridge
from team_drive.errors import DriveError


class BrokerLifecycleTests(unittest.TestCase):
    def test_idle_shutdown_sets_stop_while_admission_is_locked(self):
        broker = Broker.__new__(Broker)
        broker.clients_lock = threading.Lock()
        broker.connections = set()
        broker.config = {"idle_seconds": 1}
        broker.last_empty = 0
        broker.stop_event = mock.Mock()
        broker.stop_event.wait.return_value = False
        broker.stop_event.set.side_effect = lambda: self.assertTrue(broker.clients_lock.locked())
        broker.close = mock.Mock()
        with mock.patch("team_drive.broker.threading.Thread"), mock.patch("team_drive.broker.time.monotonic", return_value=2):
            broker.run()
        broker.stop_event.set.assert_called_once_with()
        broker.close.assert_called_once_with()

    def test_accept_after_shutdown_decision_is_closed_without_admission(self):
        broker = Broker.__new__(Broker)
        broker.stop_event = threading.Event()
        broker.clients_lock = threading.Lock()
        broker.connections = set()
        broker.config = {"max_clients": 64}
        connection = mock.Mock()

        def late_accept():
            broker.stop_event.set()
            return connection

        broker.listener = mock.Mock()
        broker.listener.accept.side_effect = late_accept
        with mock.patch("team_drive.broker.threading.Thread") as thread:
            broker.accept()
        connection.close.assert_called_once_with()
        self.assertEqual(broker.connections, set())
        thread.assert_not_called()


class BridgeStartupTests(unittest.TestCase):
    @contextlib.contextmanager
    def environment(self, metadata):
        bridge = Bridge.__new__(Bridge)
        bridge.config = {"root": Path("/source"), "base": Path("/state"), "path": Path("/config.json"),
                         "config_id": "config", "code_id": "code"}
        clock = SimpleNamespace(now=0.0)
        processes = []
        spawn_times = []
        storage = mock.Mock()
        storage.read_metadata.side_effect = lambda name: metadata(name, processes)
        channel = mock.Mock()

        def spawn(*args, **kwargs):
            process = mock.Mock()
            process.poll.return_value = 0
            processes.append(process)
            spawn_times.append(clock.now)
            return process

        def sleep(seconds):
            clock.now += seconds

        fake_time = SimpleNamespace(time=lambda: 1000, monotonic=lambda: clock.now, sleep=sleep)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("team_drive.bridge.SourceAccess"))
            stack.enter_context(mock.patch("team_drive.bridge.StateAccess", return_value=storage))
            stack.enter_context(mock.patch("team_drive.bridge.validate_state_boundaries", return_value=Path("/state")))
            stack.enter_context(mock.patch("team_drive.bridge.time", fake_time))
            stack.enter_context(mock.patch("team_drive.bridge.subprocess.Popen", side_effect=spawn))
            stack.enter_context(mock.patch("team_drive.bridge.connect_endpoint", return_value=channel))
            stack.enter_context(mock.patch("team_drive.bridge.send"))
            receive = stack.enter_context(mock.patch("team_drive.bridge.receive", return_value={"ok": True, "session_id": "session", "instance_id": "owner"}))
            yield bridge, processes, spawn_times, clock, receive

    def test_exited_election_loser_is_retried_with_rate_limit(self):
        def metadata(name, processes):
            return {"token": "credential"} if name == "endpoint.json" and len(processes) >= 2 else None

        with self.environment(metadata) as (bridge, processes, times, clock, receive):
            bridge.connect()
            self.assertEqual(bridge.instance_id, "owner")
            self.assertEqual(len(processes), 2)
            self.assertGreaterEqual(times[1] - times[0], 1)
            self.assertLess(clock.now, 30)

    def test_retries_remain_bounded_by_original_startup_deadline(self):
        with self.environment(lambda name, processes: None) as (bridge, processes, times, clock, receive):
            with self.assertRaises(DriveError) as caught:
                bridge.connect()
            self.assertEqual(caught.exception.code, "SERVICE_START_TIMEOUT")
            self.assertLessEqual(len(processes), 30)
            self.assertLess(clock.now, 30.1)
            self.assertTrue(all(later - earlier >= 1 for earlier, later in zip(times, times[1:])))

    def test_startup_error_is_reported_before_respawn(self):
        def metadata(name, processes):
            if name == "startup-error.json" and processes:
                return {"config_id": "config", "code_id": "code", "time": 1000,
                        "result": {"error": {"code": "UNSAFE_STATE", "message": "Synthetic startup refusal"}}}
            return None

        with self.environment(metadata) as (bridge, processes, times, clock, receive):
            with self.assertRaises(DriveError) as caught:
                bridge.connect()
            self.assertEqual(caught.exception.code, "UNSAFE_STATE")
            self.assertEqual(len(processes), 1)

    def test_configuration_conflict_does_not_spawn_or_retry(self):
        with self.environment(lambda name, processes: {"token": "credential"} if name == "endpoint.json" else None) as (bridge, processes, times, clock, receive):
            receive.return_value = {"ok": False, "error": {"code": "SERVICE_CONFIGURATION_CONFLICT", "message": "Different owner"}}
            with self.assertRaises(DriveError) as caught:
                bridge.connect()
            self.assertEqual(caught.exception.code, "SERVICE_CONFIGURATION_CONFLICT")
            self.assertEqual(processes, [])


if __name__ == "__main__":
    unittest.main()
