import datetime
from matplotlib import pyplot as plt
from path_helper import path_helper
import random

path_helper()

from pathlib import Path
from typing import List

from tasks.habituation_task import IblBase


from iblutil.util import setup_logger
from pybpodapi.protocol import StateMachine

from iblrig.hardware import SOFTCODE
from iblutil.spacer import Spacer


import yaml

from iblrig.panda3d.corridor.corridor import Corridor


log = setup_logger("iblrig")


with open(Path(__file__).parent.joinpath("subject_parameters.yaml")) as f:
    SUBJECT_PARAMETERS = yaml.safe_load(f)


class Session(IblBase):
    CORRIDOR_TEXTURES = [
        "pebble.jpg",
        "blackAndWhiteCircles.png",
    ]

    def __init__(self, subject: str) -> None:
        self.protocol_name = "Main task"

        super().__init__(subject=subject)

        self.corridor_idx = -1
        self.corridor = Corridor()
        # TODO:  pre-allocate this?
        self.rotary_encoder_position: List[float] = []

        self.inject_corridor(self.corridor)
        self.injection_rotary_encoder_position(self.rotary_encoder_position)

        self.previous_rewarded_textures: List[bool] = []
        self.start_time = datetime.datetime.now()

    def next_trial(self):
        """Called before every trial, including the first and before get_state_machine_trial"""

        if (
            datetime.datetime.now() - self.start_time
        ).total_seconds() > self.task_params["SESSION_LENGTH"] * 60:
            self.paths.SESSION_FOLDER.joinpath(".stop").touch()
            self.logger.critical("Time limit reached, will exit at end of next trial")

        self.rotary_encoder_position = []

        try:
            rewarded_idx = self.CORRIDOR_TEXTURES.index(
                SUBJECT_PARAMETERS["rewarded_texture"]
            )
        except ValueError as e:
            raise ValueError(
                "rewarded_texture in subject_parameters.yaml is not present in CORRIDOR_TEXTURES"
            ) from e

        self.texture_idx = (
            rewarded_idx if random.random() >= 0.5 else int(not rewarded_idx)
        )

        # Do not do more than three of the same trial type
        if self.previous_rewarded_textures[-3:] == [self.texture_idx] * 3:
            self.texture_idx = int(not self.texture_idx)

        self.previous_rewarded_textures.append(self.texture_idx)
        self.texture = self.CORRIDOR_TEXTURES[self.texture_idx]

        self.texture_rewarded = self.texture_idx == rewarded_idx
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
        solenoid_pin = 0
        sma = StateMachine(self.bpod)

        Spacer(n_pulses=random.choice([1, 2, 3, 4, 5]), tup=0.01).add_spacer_states(
            sma, "trial_start"
        )

        sma.set_global_timer(1, self.task_params.MAX_TRIAL_TIME)
        sma.set_global_timer(2, self.task_params.REWARD_ZONE_TIME)
        sma.set_global_timer(3, self.task_params.ITI_LENGTH)

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
            state_change_conditions={
                # 2,3.4 are backups in case the first one doesn't trigger
                "RotaryEncoder1_1": "reward_on1",
                "RotaryEncoder1_2": "reward_on1",
                "RotaryEncoder1_3": "reward_on1",
                "RotaryEncoder1_4": "reward_on1",
                "GlobalTimer1_End": "trigger_ITI",
                "Tup": "transition",
            },
        )

        sma.add_state(
            state_name="transition",
            state_timer=1 / self.task_params.SCREEN_REFRESH_RATE,
            state_change_conditions={
                # 2,3.4 are backups in case the first one doesn't trigger
                "RotaryEncoder1_1": "reward_on1",
                "RotaryEncoder1_2": "reward_on1",
                "RotaryEncoder1_3": "reward_on1",
                "RotaryEncoder1_4": "reward_on1",
                "GlobalTimer1_End": "trigger_ITI",
                "Tup": "trigger_panda",
            },
        )

        sma.add_state(
            state_name="reward_on1",
            # Screen will freeze for the solenoid open time, probably fine but keep an
            # eye if you need to open it for a long time
            state_timer=self.task_params.SOLENOID_OPEN_TIME,
            output_actions=[
                ("Valve1", solenoid_pin),
                ("GlobalTimerTrig", 2),
            ],  # To FPGA
            state_change_conditions={"Tup": "reward_off1"},
        )

        sma.add_state(
            state_name="reward_off1",
            # Needs a short time to turn the solenoid off.
            # JB: This timer is critical. Basically, it is the time in between two water drops.
            state_timer=self.task_params.INTER_REWARD_INTERVAL,
            output_actions=[("Valve1", 0)],
            state_change_conditions={"Tup": "reward_on2"},
        )

        sma.add_state(
            state_name="reward_on2",
            # Screen will freeze for the solenoid open time, probably fine but keep an
            # eye if you need to open it for a long time
            state_timer=self.task_params.SOLENOID_OPEN_TIME,
            output_actions=[
                ("Valve1", solenoid_pin),
                ("GlobalTimerTrig", 2),
            ],  # To FPGA
            state_change_conditions={"Tup": "reward_off2"},
        )

        sma.add_state(
            state_name="reward_off2",
            # Needs a short time to turn the solenoid off.
            state_timer=0.001,
            output_actions=[("Valve1", 0)],
            state_change_conditions={"Tup": "reward_on3"},
        )

        sma.add_state(
            state_name="reward_on3",
            # Screen will freeze for the solenoid open time, probably fine but keep an
            # eye if you need to open it for a long time
            state_timer=self.task_params.SOLENOID_OPEN_TIME,
            output_actions=[
                ("Valve1", solenoid_pin),
                ("GlobalTimerTrig", 2),
            ],  # To FPGA
            state_change_conditions={"Tup": "reward_off3"},
        )

        sma.add_state(
            state_name="reward_off3",
            # Needs a short time to turn the solenoid off.
            state_timer=0.001,
            output_actions=[("Valve1", 0)],
            state_change_conditions={"Tup": "transition_post_reward"},
        )

        sma.add_state(
            state_name="transition_post_reward",
            state_timer=1 / self.task_params.SCREEN_REFRESH_RATE,
            state_change_conditions={
                "GlobalTimer2_End": "trigger_ITI",
                "Tup": "trigger_panda_post_reward",
            },
        )

        sma.add_state(
            state_name="trigger_panda_post_reward",
            state_timer=0,
            output_actions=[("SoftCode", SOFTCODE.TRIGGER_PANDA)],
            state_change_conditions={
                "GlobalTimer2_End": "trigger_ITI",
                "Tup": "transition_post_reward",
            },
        )

        sma.add_state(
            state_name="trigger_ITI",
            state_timer=0,
            output_actions=[("SoftCode", SOFTCODE.ITI)],
            state_change_conditions={"Tup": "ITI_transition"},
        )

        sma.add_state(
            state_name="ITI_transition",
            state_timer=1 / self.task_params.SCREEN_REFRESH_RATE,
            state_change_conditions={
                "Tup": "trigger_panda_ITI",
                "GlobalTimer3_End": "exit",
            },
        )

        sma.add_state(
            state_name="trigger_panda_ITI",
            state_timer=0,
            state_change_conditions={
                "Tup": "ITI_transition",
                "GlobalTimer3_End": "exit",
            },
            output_actions=[("SoftCode", SOFTCODE.TRIGGER_PANDA)],
        )

        return sma


if __name__ == "__main__":  # pragma: no cover
    session = Session(SUBJECT_PARAMETERS["subject_id"])
    session.start_bpod()
