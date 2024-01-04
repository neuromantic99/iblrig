import sys
from pathlib import Path

parent = Path(__file__).parent.parent
sys.path.append(str(parent))


import yaml

from iblrig.base_choice_world import ChoiceWorldSession
from iblrig.panda3d.corridor.corridor import Corridor

# read defaults from task_parameters.yaml
with open(Path(__file__).parent.joinpath("task_parameters.yaml")) as f:
    DEFAULTS = yaml.safe_load(f)


class Session(ChoiceWorldSession):
    def __init__(self) -> None:
        self.protocol_name = "my- task"
        super().__init__(subject="steve")
        self.corridor = Corridor()
        self.inject_corridor(self.corridor)

    def next_trial(self):
        self.trial_num += 1

    def start_bpod(self):
        self.corridor.start()
        self.corridor.step()
        self.device_rotary_encoder.connect()
        self.run()


if __name__ == "__main__":  # pragma: no cover
    session = Session()
    session.start_bpod()
