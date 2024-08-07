"""
This module is intended to provide commonalities for all tasks.
It provides hardware mixins that can be used together with BaseSession to compose tasks
This module tries to be exclude task related logic
"""

import abc
import argparse
import os
from typing import List
import datetime
import inspect
import json
import signal
import traceback
from abc import ABC
from pathlib import Path

import scipy.interpolate
import serial
import yaml
import ibllib.io.session_params as ses_params
import iblrig
import iblrig.alyx
import iblrig.graphic as graph
import iblrig.path_helper
import pybpodapi
from iblrig import frame2TTL
from iblrig.hardware import (
    SOFTCODE,
    Bpod,
    MyRotaryEncoder,
)
from iblrig.transfer_experiments import BehaviorCopier
from iblutil.spacer import Spacer
from iblutil.util import Bunch, setup_logger
from one.api import ONE
from pybpodapi.protocol import StateMachine

from iblrig.panda3d.corridor.corridor import Corridor


# if HAS_PYSPIN:
#     import PySpin

OSC_CLIENT_IP = "127.0.0.1"


class BaseSession(ABC):
    version = None
    protocol_name: str | None = None
    base_parameters_file: Path | None = None
    is_mock = False
    extractor_tasks = None

    def __init__(
        self,
        subject=None,
        task_parameter_file=None,
        file_hardware_settings=None,
        hardware_settings=None,
        file_iblrig_settings=None,
        iblrig_settings=None,
        one=None,
        interactive=True,
        projects=None,
        procedures=None,
        stub=None,
        subject_weight_grams=None,
        append=False,
        wizard=False,
        log_level="INFO",
    ):
        """
        :param subject: The subject nickname. Required.
        :param task_parameter_file: an optional path to the task_parameters.yaml file
        :param file_hardware_settings: name of the hardware file in the settings folder, or full file path
        :param hardware_settings: an optional dictionary of hardware settings. Keys will override any keys in the file
        :param file_iblrig_settings: name of the iblrig file in the settings folder, or full file path
        :param iblrig_settings: an optional dictionary of iblrig settings. Keys will override any keys in the file
        :param one: an optional instance of ONE
        :param interactive:
        :param projects: An optional list of Alyx protocols.
        :param procedures: An optional list of Alyx procedures.
        :param subject_weight_grams: weight of the subject
        :param stub: A full path to an experiment description file containing experiment information.
        :param append: bool, if True, append to the latest existing session of the same subject for the same day
        :param fmake: (DEPRECATED) if True, only create the raw_behavior_data folder.
        """
        assert (
            self.protocol_name is not None
        ), "Protocol name must be defined by the child class"
        self.logger = None
        self._setup_loggers(level=log_level)
        self.logger.info(
            f"Running iblrig {iblrig.__version__}, pybpod version {pybpodapi.__version__}"
        )
        self.interactive = False
        self._one = one
        self.init_datetime = datetime.datetime.now()
        # Create the folder architecture and get the paths property updated
        # the template for this file is in settings/hardware_settings.yaml
        self.hardware_settings = iblrig.path_helper.load_settings_yaml(
            file_hardware_settings or "hardware_settings.yaml"
        )
        # loads in the settings: first load the files, then update with the input argument if provided
        if hardware_settings is not None:
            self.hardware_settings.update(hardware_settings)
        self.iblrig_settings = iblrig.path_helper.load_settings_yaml(
            file_iblrig_settings or "iblrig_settings.yaml"
        )
        if iblrig_settings is not None:
            self.iblrig_settings.update(iblrig_settings)
        self.wizard = wizard
        # Load the tasks settings, from the task folder or override with the input argument
        base_parameters_files = [
            task_parameter_file
            or Path(inspect.getfile(self.__class__)).parent.joinpath(
                "task_parameters.yaml"
            )
        ]
        # loop through the task hierarchy to gather parameter files
        for cls in self.__class__.__mro__:
            base_file = getattr(cls, "base_parameters_file", None)
            if base_file is not None:
                base_parameters_files.append(base_file)
        # this is a trick to remove list duplicates while preserving order, we want the highest order first
        base_parameters_files = list(
            reversed(list(dict.fromkeys(base_parameters_files)))
        )
        # now we loop into the files and update the dictionary, the latest files in the hierarchy have precedence
        self.task_params = Bunch({})
        for param_file in base_parameters_files:
            if Path(param_file).exists():
                with open(param_file) as fp:
                    params = yaml.safe_load(fp)
                if params is not None:
                    self.task_params.update(Bunch(params))
        # at last sort the dictionary so itś easier for a human to navigate the many keys
        self.task_params = Bunch(dict(sorted(self.task_params.items())))
        self.session_info = Bunch(
            {
                "NTRIALS": 0,
                "NTRIALS_CORRECT": 0,
                "PROCEDURES": procedures,
                "PROJECTS": projects,
                "SESSION_START_TIME": self.init_datetime.isoformat(),
                "SESSION_END_TIME": None,
                "SESSION_NUMBER": 0,
                "SUBJECT_NAME": subject,
                "SUBJECT_WEIGHT": subject_weight_grams,
                "TOTAL_WATER_DELIVERED": 0,
            }
        )
        # Executes mixins init methods
        self._execute_mixins_shared_function("init_mixin")
        self.paths = self._init_paths(append=append)
        self.logger.info(f"Session {self.paths.SESSION_RAW_DATA_FOLDER}")
        # Prepare the experiment description dictionary
        self.experiment_description = self.make_experiment_description_dict(
            self.protocol_name,
            self.paths.TASK_COLLECTION,
            procedures,
            projects,
            self.hardware_settings,
            stub,
            extractors=self.extractor_tasks,
        )

    def _init_paths(self, append: bool = False):
        """
        :param existing_session_path: if we append a protocol to an existing session, this is the path
        of the session in the form of /path/to/./lab/Subjects/[subject]/[date]/[number]
        :return: Bunch with keys:
        BONSAI: full path to the bonsai executable
            >>> C:\iblrigv8\Bonsai\Bonsai.exe  # noqa
        VISUAL_STIM_FOLDER: full path to the visual stim
            >>> C:\iblrigv8\visual_stim  # noqa
        LOCAL_SUBJECT_FOLDER: full path to the local subject folder
            >>> C:\iblrigv8_data\mainenlab\Subjects  # noqa
        REMOTE_SUBJECT_FOLDER: full path to the remote subject folder
            >>> Y:\Subjects  # noqa
        SESSION_FOLDER: full path to the current session:
            >>> C:\iblrigv8_data\mainenlab\Subjects\SWC_043\2019-01-01\001  # noqa
        TASK_COLLECTION: folder name of the current task
            >>> raw_task_data_00  # noqa
        SESSION_RAW_DATA_FOLDER: concatenation of the session folder and the task collection. This is where
        the task data gets written
            >>> C:\iblrigv8_data\mainenlab\Subjects\SWC_043\2019-01-01\001\raw_task_data_00  # noqa
        DATA_FILE_PATH: contains the bpod trials
            >>> C:\iblrigv8_data\mainenlab\Subjects\SWC_043\2019-01-01\001\raw_task_data_00\_iblrig_taskData.raw.jsonable  # noqa
        """
        rig_computer_paths = iblrig.path_helper.get_local_and_remote_paths(
            local_path=self.iblrig_settings["iblrig_local_data_path"],
            remote_path=self.iblrig_settings["iblrig_remote_data_path"],
            lab=self.iblrig_settings["ALYX_LAB"],
        )
        paths = Bunch({"IBLRIG_FOLDER": Path(iblrig.__file__).parents[1]})
        paths.BONSAI = paths.IBLRIG_FOLDER.joinpath("Bonsai", "Bonsai.exe")
        paths.VISUAL_STIM_FOLDER = paths.IBLRIG_FOLDER.joinpath("visual_stim")
        paths.LOCAL_SUBJECT_FOLDER = rig_computer_paths["local_subjects_folder"]
        paths.REMOTE_SUBJECT_FOLDER = rig_computer_paths["remote_subjects_folder"]
        # initialize the session path
        date_folder = paths.LOCAL_SUBJECT_FOLDER.joinpath(
            self.session_info.SUBJECT_NAME,
            self.session_info.SESSION_START_TIME[:10],
        )
        if append:
            # this is the case where we append a new protocol to an existing session
            todays_sessions = sorted(
                [d for d in date_folder.glob("*") if d.is_dir()], reverse=True
            )
            assert (
                len(todays_sessions) > 0
            ), f"Trying to chain a protocol, but no session folder found in {date_folder}"
            paths.SESSION_FOLDER = todays_sessions[0]
            paths.TASK_COLLECTION = iblrig.path_helper.iterate_collection(
                paths.SESSION_FOLDER
            )
            if self.hardware_settings.get(
                "MAIN_SYNC", False
            ) and not paths.TASK_COLLECTION.endswith("00"):
                """
                Chained protocols make little sense when Bpod is the main sync as there is no
                continuous acquisition between protocols.  Only one sync collection can be defined in
                the experiment description file.
                If you are running experiments with an ephys rig (nidq) or an external daq, you should
                correct the MAIN_SYNC parameter in the hardware settings file in ./settings/hardware_settings.yaml
                """
                raise RuntimeError(
                    "Chained protocols not supported for bpod-only sessions"
                )
        else:
            # in this case the session path is created from scratch
            numbers_folders = [
                int(f.name)
                for f in date_folder.rglob("*")
                if len(f.name) == 3 and f.name.isdigit()
            ]
            self.session_info.SESSION_NUMBER = (
                1 if len(numbers_folders) == 0 else max(numbers_folders) + 1
            )
            paths.SESSION_FOLDER = date_folder.joinpath(
                f"{self.session_info.SESSION_NUMBER:03d}"
            )
            paths.REMOTE_SESSION_PATH = (
                paths.REMOTE_SUBJECT_FOLDER
                / paths.SESSION_FOLDER.parent.parent.name
                / paths.SESSION_FOLDER.parent.name
                / paths.SESSION_FOLDER.name
            )

            os.makedirs(paths.REMOTE_SESSION_PATH, exist_ok=True)
            paths.TASK_COLLECTION = iblrig.path_helper.iterate_collection(
                paths.SESSION_FOLDER
            )

        paths.SESSION_RAW_DATA_FOLDER = paths.SESSION_FOLDER.joinpath(
            paths.TASK_COLLECTION
        )
        paths.DATA_FILE_PATH = paths.SESSION_RAW_DATA_FOLDER.joinpath(
            "_iblrig_taskData.raw.jsonable"
        )
        return paths

    def _setup_loggers(self, level="INFO", file=None):
        logger = setup_logger("iblrig", level=level, file=file)
        setup_logger("pybpodapi", level=level, file=file)
        if self.logger is None:
            self.logger = logger

    @staticmethod
    def make_experiment_description_dict(
        task_protocol: str,
        task_collection: str,
        procedures: list = None,
        projects: list = None,
        hardware_settings: dict = None,
        stub: Path = None,
        extractors: list = None,
    ):
        """
        Construct an experiment description dictionary.

        Parameters
        ----------
        task_protocol : str
            The task protocol name, e.g. _ibl_trainingChoiceWorld2.0.0.
        task_collection : str
            The task collection name, e.g. raw_task_data_00.
        procedures : list
            An optional list of Alyx procedures.
        projects : list
            An optional list of Alyx protocols.
        hardware_settings : dict
            An optional dict of hardware devices, loaded from the hardware_settings.yaml file.
        stub : dict
            An optional experiment description stub to update.
        extractors: list
            An optional list of extractor names for the task.

        Returns
        -------
        dict
            The experiment description.
        """
        description = ses_params.read_params(stub) if stub else {}
        # Add hardware devices
        if hardware_settings:
            devices = {}
            cams = hardware_settings.get("device_cameras", None)
            if cams:
                devices["cameras"] = {}
                for camera in cams:
                    if hardware_settings["device_cameras"][camera]:
                        devices["cameras"][camera] = {
                            "collection": "raw_video_data",
                            "sync_label": "audio",
                        }
            if hardware_settings.get("device_microphone", None):
                devices["microphone"] = {
                    "microphone": {"collection": task_collection, "sync_label": "audio"}
                }
        ses_params.merge_params(description, {"devices": devices})
        # Add projects and procedures
        description["procedures"] = list(
            set(description.get("procedures", []) + (procedures or []))
        )
        description["projects"] = list(
            set(description.get("projects", []) + (projects or []))
        )
        # Add sync key if required
        if (hardware_settings or {}).get(
            "MAIN_SYNC", False
        ) and "sync" not in description:
            description["sync"] = {
                "bpod": {
                    "collection": task_collection,
                    "acquisition_software": "pybpod",
                    "extension": ".jsonable",
                }
            }
        # Add task
        task = {task_protocol: {"collection": task_collection, "sync_label": "bpod"}}
        if extractors:
            assert isinstance(
                extractors, list
            ), "extractors parameter must be a list of strings"
            task[task_protocol].update({"extractors": extractors})
        if "tasks" not in description:
            description["tasks"] = [task]
        else:
            description["tasks"].append(task)
        return description

    def _make_task_parameters_dict(self):
        """
        This makes the dictionary that will be saved to the settings json file for extraction
        :return:
        """
        output_dict = dict(self.task_params)  # Grab parameters from task_params session
        output_dict.update(
            dict(self.hardware_settings)
        )  # Update dict with hardware settings from session
        output_dict.update(
            dict(self.session_info)
        )  # Update dict with session_info (subject, procedure, projects)
        patch_dict = {  # Various values added to ease transition from iblrig v7 to v8, different home may be desired
            "IBLRIG_VERSION": iblrig.__version__,
            "PYBPOD_PROTOCOL": self.protocol_name,
            "ALYX_USER": self.iblrig_settings.ALYX_USER,
            "ALYX_LAB": self.iblrig_settings.ALYX_LAB,
        }
        output_dict.update(patch_dict)
        return output_dict

    def save_task_parameters_to_json_file(self, destination_folder=None) -> Path:
        """
        Given a session object, collects the various settings and parameters of the session and outputs them to a JSON file

        Returns
        -------
        Path to the resultant JSON file
        """
        output_dict = self._make_task_parameters_dict()
        destination_folder = destination_folder or self.paths.SESSION_RAW_DATA_FOLDER
        # Output dict to json file
        json_file = destination_folder.joinpath("_iblrig_taskSettings.raw.json")
        json_file.parent.mkdir(parents=True, exist_ok=True)
        with open(json_file, "w") as outfile:
            json.dump(
                output_dict, outfile, indent=4, sort_keys=True, default=str
            )  # converts datetime objects to string
        return json_file  # PosixPath

    @property
    def one(self):
        """
        One getter
        :return:
        """
        if self._one is None:
            if self.iblrig_settings["ALYX_URL"] is None:
                return
            info_str = (
                f"alyx client with user name {self.iblrig_settings['ALYX_USER']} "
                + f"and url: {self.iblrig_settings['ALYX_URL']}"
            )
            try:
                self._one = ONE(
                    base_url=self.iblrig_settings["ALYX_URL"],
                    username=self.iblrig_settings["ALYX_USER"],
                    mode="remote",
                )
                self.logger.info("instantiated " + info_str)
            except Exception:
                self.logger.error(traceback.format_exc())
                self.logger.error("could not connect to " + info_str)
        return self._one

    def register_to_alyx(self):
        """
        Registers the session to Alyx.
        To make sure the registration is the same from the settings files and from the instantiated class
        we output the settings dictionary and register from this format directly.
        Alternatively, this function
        :return:
        """
        settings_dictionary = self._make_task_parameters_dict()
        try:
            iblrig.alyx.register_session(
                self.paths.SESSION_FOLDER, settings_dictionary, one=self.one
            )
        except Exception:
            self.logger.error(traceback.format_exc())
            self.logger.error("Could not register session to Alyx")

    def _execute_mixins_shared_function(self, pattern):
        """
        Loop over all methods of the class that start with pattern and execute them
        :param pattern:'init_mixin', 'start_mixin' or 'stop_mixin'
        :return:
        """
        method_names = [method for method in dir(self) if method.startswith(pattern)]
        methods = [
            getattr(self, method)
            for method in method_names
            if inspect.ismethod(getattr(self, method))
        ]
        for meth in methods:
            meth()

    @property
    def time_elapsed(self):
        return datetime.datetime.now() - self.init_datetime

    def mock(self):
        self.is_mock = True

    def create_session(self):
        # create the session path and save json parameters in the task collection folder
        # this will also create the protocol folder
        self.save_task_parameters_to_json_file()
        # enable file logging
        logfile = self.paths.SESSION_RAW_DATA_FOLDER.joinpath(
            "_ibl_log.info-acquisition.log"
        )
        self._setup_loggers(level=self.logger.level, file=logfile)
        # copy the acquisition stub to the remote session folder
        sc = BehaviorCopier(
            self.paths.SESSION_FOLDER,
            remote_subjects_folder=self.paths["REMOTE_SUBJECT_FOLDER"],
        )
        sc.initialize_experiment(self.experiment_description, overwrite=False)
        self.register_to_alyx()

    def run(self):
        """
        Common pre-run instructions for all tasks: singint handler for a graceful exit
        :return:
        """
        # here we make sure we connect to the hardware before writing the session to disk
        # this prevents from incrementing endlessly the session number if the hardware fails to connect
        self.start_hardware()
        self.create_session()
        if self.session_info.SUBJECT_WEIGHT is None and self.interactive:
            self.session_info.SUBJECT_WEIGHT = graph.numinput(
                "Subject weighing (gr)",
                f"{self.session_info.SUBJECT_NAME} weight (gr):",
                nullable=False,
            )

        def sigint_handler(*args, **kwargs):
            # create a signal handler for a graceful exit: create a stop flag in the session folder
            self.paths.SESSION_FOLDER.joinpath(".stop").touch()
            self.logger.critical(
                "SIGINT signal detected, will exit at the end of the trial"
            )

        # if upon starting there is a flag just remove it, this is to prevent killing a session in the egg
        if self.paths.SESSION_FOLDER.joinpath(".stop").exists():
            self.paths.SESSION_FOLDER.joinpath(".stop").unlink()

        signal.signal(signal.SIGINT, sigint_handler)
        self._run()  # runs the specific task logic ie. trial loop etc...
        # post task instructions
        self.logger.critical("Graceful exit")
        self.logger.info(f"Session {self.paths.SESSION_RAW_DATA_FOLDER}")
        self.session_info.SESSION_END_TIME = datetime.datetime.now().isoformat()
        if self.interactive and not self.wizard:
            self.session_info.POOP_COUNT = graph.numinput(
                "Poop count",
                f"{self.session_info.SUBJECT_NAME} droppings count:",
                nullable=True,
                askint=True,
            )
        self.save_task_parameters_to_json_file()
        self.register_to_alyx()
        self._execute_mixins_shared_function("stop_mixin")

    @abc.abstractmethod
    def start_hardware(self):
        """
        This methods doesn't explicitly start the mixins as the order has to be defined in the child classes
        This needs to be implemented in the child classes, and should start and connect to all hardware pieces
        """
        pass

    @abc.abstractmethod
    def _run(self):
        pass

    @staticmethod
    def extra_parser():
        """
        Optional method that specifies extra kwargs arguments to expose to the user prior running the task.
        Make sure you instantiate the parser
        :return: argparse.parser()
        """
        parser = argparse.ArgumentParser(add_help=False)
        return parser


class BpodMixin:
    def init_mixin_bpod(self, *args, **kwargs):
        self.bpod = Bpod()

    def stop_mixin_bpod(self):
        self.bpod.close()

    # These injections are not ideal but yolo, I didn't design the dumb mixin architecture
    def inject_corridor(self, corridor: Corridor):
        self.corridor = corridor

    def injection_rotary_encoder_position(self, rotary_encoder_position: List[float]):
        self.rotary_encoder_position = rotary_encoder_position

    def start_mixin_bpod(self):
        if self.hardware_settings["device_bpod"]["COM_BPOD"] is None:
            raise ValueError(
                "The value for device_bpod:COM_BPOD in "
                "settings/hardware_settings.yaml is null. Please "
                "provide a valid port name."
            )
        self.bpod = Bpod(
            self.hardware_settings["device_bpod"]["COM_BPOD"],
            # disable_behavior_ports=[1, 2, 3],
        )
        self.bpod.define_rotary_encoder_actions()
        self.bpod.set_status_led(False)

        def softcode_handler(code):
            """
            Soft codes should work with resasonable latency considering our limiting
            factor is the refresh rate of the screen which should be 16.667ms @ a framerate of 60Hz
            """
            if code == SOFTCODE.STOP_SOUND:
                self.sound["sd"].stop()
            elif code == SOFTCODE.PLAY_TONE:
                self.sound["sd"].play(self.sound["GO_TONE"], self.sound["samplerate"])
            elif code == SOFTCODE.PLAY_NOISE:
                self.sound["sd"].play(
                    self.sound["WHITE_NOISE"], self.sound["samplerate"]
                )
            elif code == SOFTCODE.TRIGGER_CAMERA:
                self.trigger_bonsai_cameras()
            elif code == SOFTCODE.TRIGGER_PANDA:
                position = self.device_rotary_encoder.rotary_encoder.current_position()
                self.rotary_encoder_position.append(position)
                self.corridor.set_camera_position(position)
                self.corridor.step()
            elif code == SOFTCODE.STORE_ENCODER_POSITION:
                # It would be better to do this with an output stream
                position = self.device_rotary_encoder.rotary_encoder.current_position()
                self.rotary_encoder_position.append(position)
            elif code == SOFTCODE.ITI:
                self.corridor.ITI()
                self.corridor.step()

        self.bpod.softcode_handler_function = softcode_handler
        assert self.bpod.is_connected
        self.logger.info("Bpod hardware module loaded: OK")

    def send_spacers(self):
        pass
        # self.logger.info("Starting task by sending a spacer signal on BNC1")
        # sma = StateMachine(self.bpod)
        # Spacer().add_spacer_states(sma, next_state="exit")
        # self.bpod.send_state_machine(sma)
        # self.bpod.run_state_machine(sma)  # Locks until state machine 'exit' is reached
        # return self.bpod.session.current_trial.export()


class Frame2TTLMixin:
    """
    Frame 2 TTL interface for state machine
    """

    def init_mixin_frame2ttl(self, *args, **kwargs):
        self.frame2ttl = None

    def start_mixin_frame2ttl(self):
        # todo assert calibration
        # todo release port on failure
        return
        if self.hardware_settings["device_frame2ttl"]["COM_F2TTL"] is None:
            raise ValueError(
                "The value for device_frame2ttl:COM_F2TTL in "
                "settings/hardware_settings.yaml is null. Please "
                "provide a valid port name."
            )
        self.frame2ttl = frame2TTL.frame2ttl_factory(
            self.hardware_settings["device_frame2ttl"]["COM_F2TTL"]
        )
        try:
            self.frame2ttl.set_thresholds(
                light=self.hardware_settings["device_frame2ttl"]["F2TTL_LIGHT_THRESH"],
                dark=self.hardware_settings["device_frame2ttl"]["F2TTL_DARK_THRESH"],
            )
            self.logger.info("Frame2TTL: Thresholds set.")
        except serial.serialutil.SerialTimeoutException as e:
            self.frame2ttl.close()
            raise e
        assert self.frame2ttl.connected
        self.logger.info("Frame2TTL module loaded: OK")


class RotaryEncoderMixin:
    """
    Rotary encoder interface for state machine
    """

    def init_mixin_rotary_encoder(self, *args, **kwargs):
        self.device_rotary_encoder = MyRotaryEncoder(
            gain=1,
            com=self.hardware_settings.device_rotary_encoder["COM_ROTARY_ENCODER"],
            connect=False,
        )

    def start_mixin_rotary_encoder(self):
        if (
            self.hardware_settings["device_rotary_encoder"]["COM_ROTARY_ENCODER"]
            is None
        ):
            raise ValueError(
                "The value for device_rotary_encoder:COM_ROTARY_ENCODER in "
                "settings/hardware_settings.yaml is null. Please "
                "provide a valid port name."
            )
        self.device_rotary_encoder.connect()
        self.logger.info("Rotary encoder module loaded: OK")


class ValveMixin:
    def init_mixin_valve(self: object):
        self.valve = Bunch({})
        # the template settings files have a date in 2099, so assume that the rig is not calibrated if that is the case
        # the assertion on calibration is thrown when starting the device
        self.valve["is_calibrated"] = (
            datetime.date.today()
            >= self.hardware_settings["device_valve"]["WATER_CALIBRATION_DATE"]
        )
        self.valve["fcn_vol2time"] = scipy.interpolate.pchip(
            self.hardware_settings["device_valve"]["WATER_CALIBRATION_WEIGHT_PERDROP"],
            self.hardware_settings["device_valve"]["WATER_CALIBRATION_OPEN_TIMES"],
        )

    def start_mixin_valve(self):
        # if the rig is not on manual settings, then the reward valve has to be calibrated to run the experiment
        # TODO: improve
        self.task_params.AUTOMATIC_CALIBRATION = False
        assert (
            self.task_params.AUTOMATIC_CALIBRATION is False
            or self.valve["is_calibrated"]
        ), """
            ##########################################
            NO CALIBRATION INFORMATION FOUND IN HARDWARE SETTINGS:
            Calibrate the rig or use a manual calibration
            PLEASE GO TO the task settings yaml file and set:
                'AUTOMATIC_CALIBRATION': false
                'CALIBRATION_VALUE' = <MANUAL_CALIBRATION>
            ##########################################"""
        # regardless of the calibration method, the reward valve time has to be lower than 1 second
        # assert (
        # self.compute_reward_time(amount_ul=1.5) < 1
        # ), """
        ##########################################
        #     REWARD VALVE TIME IS TOO HIGH!
        # Probably because of a BAD calibration file
        # Calibrate the rig or use a manual calibration
        # PLEASE GO TO the task settings yaml file and set:
        #     AUTOMATIC_CALIBRATION = False
        #     CALIBRATION_VALUE = <MANUAL_CALIBRATION>
        ##########################################"""
        self.logger.info("Water valve module loaded: OK")

    def compute_reward_time(self, amount_ul=None):
        amount_ul = (
            self.task_params.REWARD_AMOUNT_UL if amount_ul is None else amount_ul
        )
        if self.task_params.AUTOMATIC_CALIBRATION:
            return self.valve["fcn_vol2time"](amount_ul) / 1e3
        else:  # this is the manual manual calibration value
            return self.task_params.CALIBRATION_VALUE / 3 * amount_ul

    def valve_open(self, reward_valve_time):
        """
        Opens the reward valve for a given amount of time and return bpod data
        :param reward_valve_time:
        :return:
        """
        sma = StateMachine(self.bpod)
        sma.add_state(
            state_name="valve_open",
            state_timer=reward_valve_time,
            output_actions=[("Valve1", 255), ("BNC1", 255)],  # To FPGA
            state_change_conditions={"Tup": "exit"},
        )
        self.bpod.send_state_machine(sma)
        self.bpod.run_state_machine(sma)  # Locks until state machine 'exit' is reached
        return self.bpod.session.current_trial.export()
