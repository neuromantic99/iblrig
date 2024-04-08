"""
This modules extends the base_tasks modules by providing task logic around the Choice World protocol
"""

import datetime
from pathlib import Path
from typing import List

import yaml


from path_helper import path_helper

# Allows you to import from tasks
path_helper()

from tasks.ibl_base import IblBase


from iblutil.util import setup_logger
from pybpodapi.protocol import StateMachine

from iblrig.hardware import SOFTCODE


log = setup_logger("iblrig")


HERE = Path(__file__).parent.resolve()

with open(Path(__file__).parent.joinpath("subject_parameters.yaml")) as f:
    SUBJECT_PARAMETERS = yaml.safe_load(f)


class Session(IblBase):

    def __init__(self, subject: str) -> None:
        self.protocol_name = self.task_params["TASK_NAME"]
        super().__init__(subject=subject)
        self.rotary_encoder_position: List[float] = []
        self.injection_rotary_encoder_position(self.rotary_encoder_position)
        self.start_time = datetime.datetime.now()

    def next_trial(self):
        """Called before every trial, including the first and before get_state_machine_trial"""

        if (datetime.datetime.now() - self.start_time).total_seconds > self.task_params[
            "SESSION_LENGTH"
        ] / 60:
            self.paths.SESSION_FOLDER.joinpath(".stop").touch()
            self.logger.critical("Time limit reached, will exit at end of next trial")

        self.rotary_encoder_position = []
        self.trial_num += 1

    def start_bpod(self):
        self.run()

    def get_state_machine_trial(self, i):
        sma = StateMachine(self.bpod)
        sma.set_global_timer(1, 5)
        sma.set_global_timer(2, 25)

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
    session = Session(SUBJECT_PARAMETERS.subject_id)
    session.start_bpod()
    # Required to close the connection to the RE and not have to
    # replug USB on next run
    session.device_rotary_encoder.rotary_encoder.disable_stream()
    session.device_rotary_encoder.rotary_encoder.close()
