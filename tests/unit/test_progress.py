"""
tests/test_progress.py
~~~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.progress — thread-local callback emitter.
"""

from __future__ import annotations

import threading

from finamt import progress as _progress


class TestSetAndClearCallback:
    def test_set_callback_registered(self):
        calls = []
        _progress.set_callback(calls.append)
        _progress.emit("hello")
        _progress.clear_callback()
        assert "hello" in calls

    def test_clear_callback_stops_forwarding(self):
        calls = []
        _progress.set_callback(calls.append)
        _progress.clear_callback()
        _progress.emit("ignored")
        assert calls == []

    def test_emit_without_callback_does_not_raise(self, capsys):
        _progress.clear_callback()
        _progress.emit("stdout only")
        captured = capsys.readouterr()
        assert "stdout only" in captured.out


class TestEmitForwarding:
    def test_emit_calls_callback_with_message(self):
        received = []
        _progress.set_callback(received.append)
        _progress.emit("test message")
        _progress.clear_callback()
        assert received == ["test message"]

    def test_emit_multiple_messages(self):
        received = []
        _progress.set_callback(received.append)
        for msg in ("a", "b", "c"):
            _progress.emit(msg)
        _progress.clear_callback()
        assert received == ["a", "b", "c"]

    def test_callback_exception_does_not_propagate(self):
        def bad_cb(msg):
            raise RuntimeError("boom")

        _progress.set_callback(bad_cb)
        # Should not raise
        _progress.emit("safe")
        _progress.clear_callback()

    def test_callback_is_thread_local(self):
        """Callback registered in one thread must not fire in another."""
        main_calls = []
        other_calls = []

        _progress.set_callback(main_calls.append)

        def _in_thread():
            # Empty callback in this thread
            _progress.clear_callback()
            _progress.set_callback(other_calls.append)
            _progress.emit("from-thread")
            _progress.clear_callback()

        t = threading.Thread(target=_in_thread)
        t.start()
        t.join()

        _progress.emit("from-main")
        _progress.clear_callback()

        assert "from-main" in main_calls
        assert "from-thread" not in main_calls
        assert "from-thread" in other_calls
