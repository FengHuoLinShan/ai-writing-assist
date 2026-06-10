import pytest

from core.container import Injected, get, register, reset


def setup_function():
    reset()


def teardown_function():
    reset()


def test_register_and_get():
    register("test_svc", lambda: "hello")
    assert get("test_svc")() == "hello"


def test_get_missing_raises_keyerror():
    reset()
    with pytest.raises(KeyError, match="not registered"):
        get("nonexistent")


def test_duplicate_register_raises_valueerror():
    register("dup", "a")
    with pytest.raises(ValueError, match="already registered"):
        register("dup", "b")


def test_reset_clears_all():
    register("x", 1)
    reset()
    with pytest.raises(KeyError):
        get("x")


class TestInjected:
    def setup_method(self):
        reset()

    def test_injected_descriptor_resolves(self):
        register("world.list_characters", lambda: ["char1"])

        class MyService:
            list_chars = Injected("world.list_characters")

        svc = MyService()
        assert svc.list_chars() == ["char1"]

    def test_injected_descriptor_missing_raises(self):
        class MyService:
            missing = Injected("not.registered")

        svc = MyService()
        with pytest.raises(KeyError):
            svc.missing
