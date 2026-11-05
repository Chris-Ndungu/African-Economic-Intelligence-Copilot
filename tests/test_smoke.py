import backend
import copilot_core


def test_packages_import():
    assert copilot_core.__name__ == "copilot_core"
    assert backend.__name__ == "backend"
