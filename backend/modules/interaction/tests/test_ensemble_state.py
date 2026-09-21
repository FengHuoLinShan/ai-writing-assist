from types import SimpleNamespace
from uuid import uuid4

from modules.interaction.ensemble_v2 import restore_environment


def test_selected_branch_environment_restores_resources_without_sibling_state():
    first, second, sibling = uuid4(), uuid4(), uuid4()
    actor = str(uuid4())
    prior = {
        actor: SimpleNamespace(
            message_node_id=second,
            state_json={
                "environment": {
                    "resource_holders": {"钥匙": actor},
                    "participants": [actor],
                    "revision": 2,
                },
                "observations": [{"action": "收下钥匙"}],
            },
        )
    }
    state = restore_environment(
        prior, [SimpleNamespace(id=first), SimpleNamespace(id=second)]
    )
    assert state["resource_holders"] == {"钥匙": actor}
    assert str(sibling) not in str(state)
    state["resource_holders"].clear()
    assert prior[actor].state_json["environment"]["resource_holders"] == {"钥匙": actor}
