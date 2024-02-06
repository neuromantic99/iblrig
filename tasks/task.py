"""
This modules extends the base_tasks modules by providing task logic around the Choice World protocol
"""

import abc
import json
import sys
import time
from pathlib import Path

parent = Path(__file__).parent.parent
sys.path.append(str(parent))


import numpy as np
import pandas as pd
from iblutil.util import setup_logger
from pybpodapi.protocol import StateMachine

import iblrig.base_tasks
import iblrig.graphic
from iblrig import misc
from iblrig.hardware import SOFTCODE


import yaml

from iblrig.panda3d.corridor.corridor import Corridor

log = setup_logger("iblrig")

# TODO: make settings yaml
REWARD_ZONE_TIME = 1.5
ITI_LENGTH = 1
SCREEN_REFRESH_RATE = 60  # Hz
NUMBER_TURNS_TO_REWARD = 2


class IblBase(
    iblrig.base_tasks.BaseSession,
    iblrig.base_tasks.BpodMixin,
    iblrig.base_tasks.Frame2TTLMixin,
    iblrig.base_tasks.RotaryEncoderMixin,
    iblrig.base_tasks.ValveMixin,
):
    base_parameters_file = Path(__file__).parent.parent.joinpath(
        "iblrig/base_choice_world_params.yaml"
    )

    def __init__(self, subject: str, delay_secs: int = 0):
        super().__init__(subject=subject, task_parameter_file=self.base_parameters_file)
        self.task_params["SESSION_DELAY_START"] = delay_secs

        self.trial_num = -1
        self.block_num = -1
        self.block_trial_num = -1
        # init the tables, there are 2 of them: a trials table and a ambient sensor data table

        # TODO: Fix this table
        NTRIALS_INIT = 10
        self.trials_table = pd.DataFrame(
            {
                "reward_amount": np.zeros(NTRIALS_INIT) * np.NaN,
                "reward_valve_time": np.zeros(NTRIALS_INIT) * np.NaN,
                "trial_correct": np.zeros(NTRIALS_INIT, dtype=bool),
                "trial_num": np.zeros(NTRIALS_INIT, dtype=np.int16),
            }
        )

        self.ambient_sensor_table = pd.DataFrame(
            {
                "Temperature_C": np.zeros(NTRIALS_INIT) * np.NaN,
                "AirPressure_mb": np.zeros(NTRIALS_INIT) * np.NaN,
                "RelativeHumidity": np.zeros(NTRIALS_INIT) * np.NaN,
            }
        )

    def start_hardware(self):
        """
        In this step we explicitly run the start methods of the various mixins.
        The super class start method is overloaded because we need to start the different hardware pieces in order
        """
        if not self.is_mock:
            self.start_mixin_frame2ttl()
            self.start_mixin_bpod()
            self.start_mixin_valve()
            self.start_mixin_rotary_encoder()

    def _run(self):
        """
        This is the method that runs the task with the actual state machine
        :return:
        """
        # make the bpod send spacer signals to the main sync clock for protocol discovery

        # This is the run

        self.send_spacers()
        time_last_trial_end = time.time()
        for i in range(self.task_params.NTRIALS):  # Main loop
            # t_overhead = time.time()
            self.next_trial()
            log.info(f"Starting trial: {i}")
            # =============================================================================
            #     Start state machine definition
            # =============================================================================
            sma = self.get_state_machine_trial(i)
            log.info("Sending state machine to bpod")
            # Send state machine description to Bpod device
            self.bpod.send_state_machine(sma)
            # t_overhead = time.time() - t_overhead
            # Run state machine
            dt = (
                self.task_params.ITI_DELAY_SECS
                - 0.5
                - (time.time() - time_last_trial_end)
            )
            # wait to achieve the desired ITI duration
            if dt > 0:
                time.sleep(dt)
            log.info("running state machine")
            self.bpod.run_state_machine(
                sma
            )  # Locks until state machine 'exit' is reached
            time_last_trial_end = time.time()
            self.trial_completed(self.bpod.session.current_trial.export())
            self.show_trial_log()
            while self.paths.SESSION_FOLDER.joinpath(".pause").exists():
                time.sleep(1)
            if self.paths.SESSION_FOLDER.joinpath(".stop").exists():
                self.paths.SESSION_FOLDER.joinpath(".stop").unlink()
                break

    @abc.abstractmethod
    def next_trial(self):
        pass

    @property
    def reward_amount(self):
        return self.task_params.REWARD_AMOUNT_UL

    def trial_completed(self, bpod_data):
        # if the reward state has not been triggered, null the reward
        if np.isnan(bpod_data["States timestamps"]["reward"][0][0]):
            self.trials_table.at[self.trial_num, "reward_amount"] = 0
        self.trials_table.at[self.trial_num, "reward_valve_time"] = self.reward_time
        # update cumulative reward value
        self.session_info.TOTAL_WATER_DELIVERED += self.trials_table.at[
            self.trial_num, "reward_amount"
        ]
        self.session_info.NTRIALS += 1
        # SAVE TRIAL DATA
        save_dict = self.trials_table.iloc[self.trial_num].to_dict()
        save_dict["behavior_data"] = bpod_data
        # Dump and save
        with open(self.paths["DATA_FILE_PATH"], "a") as fp:
            fp.write(json.dumps(save_dict) + "\n")
        # this is a flag for the online plots. If online plots were in pyqt5, there is a file watcher functionality
        Path(self.paths["DATA_FILE_PATH"]).parent.joinpath("new_trial.flag").touch()
        # If more than 42 trials save transfer_me.flag
        if self.trial_num == 42:
            self.paths.SESSION_FOLDER.joinpath("transfer_me.flag").touch()
            # todo: add number of devices in there
        self.check_sync_pulses(bpod_data=bpod_data)

    def check_sync_pulses(self, bpod_data):
        # todo move this in the post trial when we have a task flow
        if not self.bpod.is_connected:
            return
        events = bpod_data["Events timestamps"]
        ev_bnc1 = misc.get_port_events(events, name="BNC1")
        ev_bnc2 = misc.get_port_events(events, name="BNC2")
        ev_port1 = misc.get_port_events(events, name="Port1")
        NOT_FOUND = "COULD NOT FIND DATA ON {}"
        bnc1_msg = NOT_FOUND.format("BNC1") if not ev_bnc1 else "OK"
        bnc2_msg = NOT_FOUND.format("BNC2") if not ev_bnc2 else "OK"
        port1_msg = NOT_FOUND.format("Port1") if not ev_port1 else "OK"
        warn_msg = f"""
            ##########################################
                    NOT FOUND: SYNC PULSES
            ##########################################
            VISUAL STIMULUS SYNC: {bnc1_msg}
            SOUND SYNC: {bnc2_msg}
            CAMERA SYNC: {port1_msg}
            ##########################################"""
        if not ev_bnc1 or not ev_bnc2 or not ev_port1:
            log.warning(warn_msg)

    def show_trial_log(self, extra_info=""):
        trial_info = self.trials_table.iloc[self.trial_num]
        msg = f"""
Session {self.paths.SESSION_RAW_DATA_FOLDER}
##########################################
TRIAL NUM:            {trial_info.trial_num}
{extra_info}
WATER DELIVERED:      {np.round(self.session_info.TOTAL_WATER_DELIVERED, 3)} µl
TIME FROM START:      {self.time_elapsed}
##########################################"""
        log.info(msg)

    @property
    def iti_reward(self, assert_calibration=True):
        """
        Returns the ITI time that needs to be set in order to achieve the desired ITI,
        by subtracting the time it takes to give a reward from the desired ITI.
        """
        if assert_calibration:
            assert (
                "REWARD_VALVE_TIME" in self.calibration
            ), "Reward valve time not calibrated"
        return self.task_params.ITI_CORRECT - self.calibration.get(
            "REWARD_VALVE_TIME", None
        )

    """
    Those are the properties that are used in the state machine code
    """

    @property
    def reward_time(self) -> float:
        return self.compute_reward_time(
            amount_ul=self.trials_table.at[self.trial_num, "reward_amount"]
        )

    @property
    def quiescent_period(self) -> float:
        return self.trials_table.at[self.trial_num, "quiescent_period"]

    @property
    def position(self):
        return self.trials_table.at[self.trial_num, "position"]

    @property
    def event_error(self):
        return self.device_rotary_encoder.THRESHOLD_EVENTS[self.position]

    @property
    def event_reward(self):
        return self.device_rotary_encoder.THRESHOLD_EVENTS[-self.position]


# read defaults from task_parameters.yaml
with open(Path(__file__).parent.joinpath("task_parameters.yaml")) as f:
    DEFAULTS = yaml.safe_load(f)


class Session(IblBase):
    CORRIDOR_TEXTURES = [
        "pinkBars.png",
        "blueTriangles.jpg",
        "horGrat.jpg",
    ]

    def __init__(self) -> None:
        self.protocol_name = "my-task"
        super().__init__(subject="steve")
        self.corridor_idx = -1
        self.corridor = Corridor()
        self.inject_corridor(self.corridor)

    def next_trial(self):
        self.device_rotary_encoder.reset_position()
        self.trial_num += 1
        self.corridor_idx += 1
        self.corridor.start_trial(self.CORRIDOR_TEXTURES[self.corridor_idx])

    def start_bpod(self):
        self.corridor.start()
        self.corridor.step()
        self.run()

    def get_state_machine_trial(self, i):
        sma = StateMachine(self.bpod)

        sma.add_state(
            state_name="trial_start",
            state_timer=0,
            state_change_conditions={"Tup": "call_panda"},
            output_actions=[("GlobalTimerTrig", 1), ("PWM1", 0)],
        )

        sma.add_state(
            state_name="reset_rotary_encoder",
            state_timer=0,
            output_actions=[self.bpod.actions.rotary_encoder_reset],
            state_change_conditions={"Tup": "call_panda"},
        )

        sma.add_state(
            state_name="call_panda",
            state_timer=0,
            output_actions=[("SoftCode", SOFTCODE.TRIGGER_PANDA)],
            state_change_conditions={"Tup": "transition"},
        )

        sma.add_state(
            state_name="transition",
            state_timer=1 / SCREEN_REFRESH_RATE,
            state_change_conditions={
                "RotaryEncoder1_1": "reward",
                "Tup": "call_panda",
            },
        )

        # TODO: This may need to be called multiple times if you don't want to hold the spout open for
        # the whole time
        sma.add_state(
            state_name="reward",
            state_timer=1,
            output_actions=[
                ("SoftCode", SOFTCODE.REWARD_ON)
            ],  # Change to actual action
            state_change_conditions={"Tup": "exit"},
        )

        sma.add_state(
            state_name="reward_off",
            state_timer=REWARD_ZONE_TIME,
            output_actions=[("SoftCode", SOFTCODE.ITI)],
            state_change_conditions={"Tup": "ITI"},
        )

        sma.add_state(
            state_name="ITI",
            state_timer=ITI_LENGTH,
            state_change_conditions={"Tup": "exit"},
        )

        return sma


if __name__ == "__main__":  # pragma: no cover
    session = Session()
    session.start_bpod()
