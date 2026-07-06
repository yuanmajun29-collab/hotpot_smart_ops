"""Store-and-forward buffer for IoT readings (LOSS-502).

Per Codex P1A guidance: real-device ingestion needs short local buffering +
replay safety so disconnects never lose readings (不丢读数). Disk-backed,
bounded, replay-safe, survives process restart.
"""
from __future__ import annotations


def test_enqueue_and_replay_all_delivered(tmp_path):
    from edge.store_forward import StoreAndForwardBuffer
    buf = StoreAndForwardBuffer(tmp_path / "buf.jsonl")
    buf.enqueue({"sensor_id": "s1", "value": 1})
    buf.enqueue({"sensor_id": "s1", "value": 2})
    assert len(buf) == 2
    delivered = []
    n = buf.replay(lambda item: bool(delivered.append(item)) or True)
    assert n == 2
    assert len(buf) == 0
    assert [d["value"] for d in delivered] == [1, 2]


def test_replay_failure_retains_everything(tmp_path):
    from edge.store_forward import StoreAndForwardBuffer
    buf = StoreAndForwardBuffer(tmp_path / "b.jsonl")
    buf.enqueue({"value": 1})
    buf.enqueue({"value": 2})
    n = buf.replay(lambda item: False)  # sink down → all fail
    assert n == 0
    assert len(buf) == 2  # nothing lost


def test_replay_partial_keeps_remaining_in_order(tmp_path):
    from edge.store_forward import StoreAndForwardBuffer
    buf = StoreAndForwardBuffer(tmp_path / "b.jsonl")
    for v in (1, 2, 3):
        buf.enqueue({"value": v})
    n = buf.replay(lambda item: item["value"] < 3)  # 1,2 ok; 3 fails
    assert n == 2
    assert len(buf) == 1
    rem = []
    buf.replay(lambda item: bool(rem.append(item)) or True)
    assert [r["value"] for r in rem] == [3]


def test_persistence_across_instances(tmp_path):
    from edge.store_forward import StoreAndForwardBuffer
    p = tmp_path / "b.jsonl"
    StoreAndForwardBuffer(p).enqueue({"value": 9})
    assert len(StoreAndForwardBuffer(p)) == 1  # reloaded from disk


def test_bounded_drops_oldest(tmp_path):
    from edge.store_forward import StoreAndForwardBuffer
    buf = StoreAndForwardBuffer(tmp_path / "b.jsonl", max_items=2)
    for v in (1, 2, 3):
        buf.enqueue({"value": v})
    assert len(buf) == 2
    got = []
    buf.replay(lambda item: bool(got.append(item["value"])) or True)
    assert got == [2, 3]  # oldest (1) dropped


def test_bridge_forward_buffers_on_hub_failure_and_replays(tmp_path):
    from edge.iot_mock.mqtt_bridge import MqttHubBridge
    bridge = MqttHubBridge("store_yuhuan", "http://x", "mqtt://x", {"sensors": []},
                           buffer_path=tmp_path / "b.jsonl")

    class FakeHub:
        def __init__(self):
            self.posted = []
            self.fail = True

        def post_event(self, ev):
            if self.fail:
                raise RuntimeError("hub down")
            self.posted.append(ev)

    fake = FakeHub()
    bridge.hub = fake
    ev = {"event_type": "iot_temperature_reading", "value": 1}
    bridge._forward(ev)
    assert len(bridge.buffer) == 1  # buffered, not lost

    fake.fail = False
    n = bridge.replay_buffer()
    assert n == 1
    assert len(bridge.buffer) == 0
    assert fake.posted == [ev]


def test_bridge_buffers_when_hub_returns_false_without_exception(tmp_path):
    from edge.iot_mock.mqtt_bridge import MqttHubBridge
    bridge = MqttHubBridge("store_yuhuan", "http://x", "mqtt://x", {"sensors": []},
                           buffer_path=tmp_path / "b.jsonl")

    class FakeHub:
        def __init__(self):
            self.posted = []

        def try_post_event(self, ev):
            return False

        def post_event(self, ev):
            self.posted.append(ev)
            return True

    fake = FakeHub()
    bridge.hub = fake
    ev = {"event_type": "iot_temperature_reading", "value": 7}
    bridge._forward(ev)
    assert len(bridge.buffer) == 1
    assert fake.posted == []


def test_edge_hub_try_post_event_does_not_enqueue(tmp_path):
    from common.hub_client import EdgeHubClient

    client = EdgeHubClient(
        "http://127.0.0.1:9",
        "store_yuhuan",
        queue_db=tmp_path / "edge_queue.db",
    )
    ok = client.try_post_event({"event_type": "iot_temperature_reading"})
    assert ok is False
    assert client.pending_count() == 0
