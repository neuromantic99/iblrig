import abc
from dataclasses import dataclass
import json
import sys
import time
from pathlib import Path
from typing import List
from dataclasses import asdict


parent = Path(__file__).parent.parent
sys.path.append(str(parent))

import numpy as np
import pandas as pd

import iblrig.base_tasks
import iblrig.graphic
from iblrig import misc
from iblutil.util import setup_logger
from iblrig.hardware import SOFTCODE


@dataclass
class StateInfo:
    name: str
    start_time: float
    end_time: float


@dataclass
class EventInfo:
    name: str
    start_time: float


@dataclass
class TrialInfo:
    trial_start_time: float
    trial_end_time: float
    pc_timestamp: str
    states_info: List[StateInfo]
    events_info: List[EventInfo]
    rotary_encoder_position: List[float]
    texture: str
    texture_rewarded: bool


log = setup_logger("iblrig")


class IblBase(
    iblrig.base_tasks.BaseSession,
    iblrig.base_tasks.BpodMixin,
    iblrig.base_tasks.Frame2TTLMixin,
    iblrig.base_tasks.RotaryEncoderMixin,
    iblrig.base_tasks.ValveMixin,
):
    base_parameters_file = Path(__file__).parent.parent.joinpath(
        "tasks/task_parameters.yaml"
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
        self.texture = ""
        self.texture_rewarded = False

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
            # Run state machine

            # Used to be an ITI delay here which can be readded if needed
            log.info("running state machine")
            self.bpod.run_state_machine(
                sma
            )  # Locks until state machine 'exit' is reached
            time_last_trial_end = time.time()
            self.trial_completed(self.bpod.session.current_trial.export())

            # self.show_trial_log()

            self.save_trial_data(i)

            while self.paths.SESSION_FOLDER.joinpath(".pause").exists():
                time.sleep(1)
            if self.paths.SESSION_FOLDER.joinpath(".stop").exists():
                self.paths.SESSION_FOLDER.joinpath(".stop").unlink()
                break

    def save_trial_data(self, i: int) -> None:
        trial = self.bpod.session.current_trial
        trial_info = TrialInfo(
            trial_start_time=trial.trial_start_timestamp,
            trial_end_time=trial.trial_end_timestamp,
            pc_timestamp=trial.pc_timestamp.isoformat(),
            states_info=[
                StateInfo(state.state_name, state.start_timestamp, state.end_timestamp)
                for state in trial.states_occurrences
            ],
            events_info=[
                EventInfo(event.event_name, event.host_timestamp)
                for event in trial.events_occurrences
            ],
            rotary_encoder_position=self.rotary_encoder_position,
            texture=self.texture,
            texture_rewarded=self.texture_rewarded,
        )

        with open(self.paths.SESSION_FOLDER / f"trial{i}.json", "w") as f:
            json.dump(asdict(trial_info), f)

    @abc.abstractmethod
    def next_trial(self):
        pass

    @property
    def reward_amount(self):
        return self.task_params.REWARD_AMOUNT_UL

    def trial_completed(self, bpod_data):
        pass

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
