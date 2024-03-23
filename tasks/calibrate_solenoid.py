"""
This modules extends the base_tasks modules by providing task logic around the Choice World protocol
"""

from path_helper import path_helper

# Allows you to import from tasks
path_helper()

import sys
from pathlib import Path

from tasks.ibl_base import IblBase


parent = Path(__file__).parent.parent
sys.path.append(str(parent))


from iblutil.util import setup_logger
from pybpodapi.protocol import StateMachine

from iblrig.hardware import SOFTCODE


import yaml

from iblrig.panda3d.corridor.corridor import Corridor


log = setup_logger("iblrig")


# read defaults from task_parameters.yaml
with open(Path(__file__).parent.joinpath("task_parameters.yaml")) as f:
    DEFAULTS = yaml.safe_load(f)


class Session(IblBase):
    CORRIDOR_TEXTURES = [
        "verticalGrating.jpg",
        "pinkBars.png",
        "blueTriangles.jpg",
    ]

    def __init__(self, subject: str) -> None:
        self.protocol_name = "habitutation"
        super().__init__(subject=subject)

    def next_trial(self):
        """Called before every trial, including the first and before get_state_machine_trial"""
        self.rotary_encoder_position = []
        self.trial_num += 1

    def start_bpod(self):  #
        # self.device_rotary_encoder.rotary_encoder.close()
        self.run()

    def get_state_machine_trial(self, i):
        sma = StateMachine(self.bpod)

        sma.add_state(
            state_name="start",
            state_timer=0,
            state_change_conditions={
                "Tup": "open",
            },
        )

        sma.add_state(
            state_name="open",
            state_timer=self.task_params.SOLENOID_OPEN_TIME * 10,
            output_actions=[
                ("Valve1", 255),  # 255 is the voltage that you send to the solenoid
            ],
            state_change_conditions={
                "Tup": "close",
            },
        )

        sma.add_state(
            state_name="close",
            state_timer=0,
            state_change_conditions={"Tup": "exit"},
            output_actions=[
                ("Valve1", 0),  # set solenoid voltage to 0
            ],
        )
        return sma


if __name__ == "__main__":  # pragma: no cover

    session = Session("")
    session.start_bpod()
    # Required to close the connection to the RE and not have to
    # replug USB on next run
    session.device_rotary_encoder.rotary_encoder.disable_stream()
    session.device_rotary_encoder.rotary_encoder.close()
