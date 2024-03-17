"""
This modules extends the base_tasks modules by providing task logic around the Choice World protocol
"""

import sys
from pathlib import Path
from typing import List

from tasks.habituation_task import IblBase


parent = Path(__file__).parent.parent
sys.path.append(str(parent))


import numpy as np
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
        self.texture_idx = np.random.randint(0, len(self.CORRIDOR_TEXTURES))
        self.texture_rewarded = self.texture_idx != 0
        self.texture = self.CORRIDOR_TEXTURES[self.texture_idx]
        self.device_rotary_encoder.reset_position()
        self.device_rotary_encoder.set_thresholds()
        self.trial_num += 1
        self.corridor_idx += 1
        print(f"Starting trial with texture: {self.texture}")
        self.corridor.start_trial(self.texture)
        self.injection_rotary_encoder_position(self.rotary_encoder_position)

    def start_bpod(self):
        self.corridor.start()
        self.corridor.step()
        self.run()

    def get_state_machine_trial(self, i):
        solenoid_pin = 255 if self.texture_rewarded else 0
        sma = StateMachine(self.bpod)
        sma.set_global_timer(1, self.task_params.MAX_TRIAL_TIME)
        sma.set_global_timer(2, self.task_params.REWARD_ZONE_TIME)

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
            state_change_conditions={"Tup": "trigger_panda"},
        )

        sma.add_state(
            state_name="trigger_panda",
            state_timer=0,
            output_actions=[("SoftCode", SOFTCODE.TRIGGER_PANDA)],
            state_change_conditions={"Tup": "transition"},
        )

        sma.add_state(
            state_name="transition",
            state_timer=1 / self.task_params.SCREEN_REFRESH_RATE,
            state_change_conditions={
                "RotaryEncoder1_1": "reward_on",
                "GlobalTimer1_End": "exit",
                "GlobalTimer2_End": "trigger_ITI",
                "Tup": "trigger_panda",
            },
        )

        sma.add_state(
            state_name="reward_on",
            # Screen will freeze for the solenoid open time, probably fine but keep an
            # eye if you need to open it for a long time
            state_timer=self.task_params.SOLENOID_OPEN_TIME,
            output_actions=[
                ("Valve1", solenoid_pin),
                ("GlobalTimerTrig", 2),
            ],  # To FPGA
            state_change_conditions={"Tup": "reward_off"},
        )

        sma.add_state(
            state_name="reward_off",
            # Needs a short time to turn the solenoid off.
            state_timer=0.001,
            output_actions=[("Valve1", 0)],
            state_change_conditions={"Tup": "transition"},
        )

        sma.add_state(
            state_name="trigger_ITI",
            state_timer=0,
            output_actions=[("SoftCode", SOFTCODE.ITI)],
            state_change_conditions={"Tup": "ITI"},
        )

        sma.add_state(
            state_name="ITI",
            state_timer=self.task_params.ITI_LENGTH,
            state_change_conditions={"Tup": "exit"},
        )

        return sma


if __name__ == "__main__":  # pragma: no cover
    session = Session()
    session.start_bpod()
