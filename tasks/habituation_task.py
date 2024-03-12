"""
This modules extends the base_tasks modules by providing task logic around the Choice World protocol
"""

from dataclasses import dataclass
import sys
from pathlib import Path
from typing import List

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

    def __init__(self) -> None:
        self.protocol_name = "my-task"
        super().__init__(subject="steve")
        self.corridor_idx = -1
        self.corridor = Corridor()
        # TODO:  pre-allocate this?
        self.rotary_encoder_position: List[float] = []

        self.inject_corridor(self.corridor)
        self.injection_rotary_encoder_position(self.rotary_encoder_position)

    def next_trial(self):
        """Called before every trial, including the first and before get_state_machine_trial"""
        self.rotary_encoder_position = []
        self.trial_num += 1

    def start_bpod(self):
        self.run()

    def get_state_machine_trial(self, i):
        sma = StateMachine(self.bpod)
        sma.set_global_timer(1, 25)
        sma.set_global_timer(2, 5)

        sma.add_state(
            state_name="trial_start",
            state_timer=0,
            state_change_conditions={"Tup": "reset_rotary_encoder"},
            output_actions=[
                ("GlobalTimerTrig", 1),
            ],
        )

        sma.add_state(
            state_name="reset_rotary_encoder",
            state_timer=0,
            output_actions=[self.bpod.actions.rotary_encoder_reset],
            state_change_conditions={"Tup": "store_encoder_position"},
        )

        sma.add_state(
            state_name="store_encoder_position",
            state_timer=0,
            output_actions=[("SoftCode", SOFTCODE.STORE_ENCODER_POSITION)],
            state_change_conditions={"Tup": "transition"},
        )

        sma.add_state(
            state_name="transition",
            state_timer=1 / 10,
            state_change_conditions={
                "GlobalTimer1_End": "reward_on",
                "GlobalTimer2_End": "exit",
                "Tup": "store_encoder_position",
            },
        )

        sma.add_state(
            state_name="reward_on",
            state_timer=self.task_params.SOLENOID_OPEN_TIME,
            output_actions=[
                ("Valve1", 255),
                ("GlobalTimerTrig", 2),
            ],  # To FPGA
            state_change_conditions={"Tup": "reward_off"},
        )

        sma.add_state(
            state_name="reward_off",
            # Short timer to actually send voltage to solenoid
            state_timer=0.001,
            output_actions=[("Valve1", 0)],
            state_change_conditions={"Tup": "transition"},
        )

        return sma


if __name__ == "__main__":  # pragma: no cover
    session = Session()
    session.start_bpod()
