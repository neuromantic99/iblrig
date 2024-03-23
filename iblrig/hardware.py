"""
This modules contains hardware classes used to interact with modules.
"""

import os
import re
import shutil
import struct
import subprocess
import threading
import time
from enum import IntEnum
from pathlib import Path

import numpy as np
import serial
import sounddevice as sd
from serial.tools import list_ports
from iblrig.rotary_encoder_module import RotaryEncoderModule

import iblrig.path_helper


from iblrig.tools import static_vars
from iblutil.util import Bunch, setup_logger
from pybpod_rotaryencoder_module.module import RotaryEncoder
from pybpodapi.bpod.bpod_io import BpodIO

HARDWARE_SETTINGS = iblrig.path_helper.load_settings_yaml("hardware_settings.yaml")


SOFTCODE = IntEnum(
    "SOFTCODE",
    [
        "STOP_SOUND",
        "PLAY_TONE",
        "PLAY_NOISE",
        "TRIGGER_CAMERA",
        "TRIGGER_PANDA",
        "STORE_ENCODER_POSITION",
        "ITI",
    ],
)

log = setup_logger("iblrig")


class Bpod(BpodIO):
    can_control_led = True
    _instances = {}
    _lock = threading.Lock()
    _is_initialized = False

    def __new__(cls, *args, **kwargs):
        serial_port = args[0] if len(args) > 0 else ""
        serial_port = kwargs.get("serial_port", serial_port)
        with cls._lock:
            instance = Bpod._instances.get(serial_port, None)
            if instance:
                return instance
            instance = super().__new__(cls)
            Bpod._instances[serial_port] = instance
            return instance

    def __init__(self, *args, skip_initialization: bool = False, **kwargs):
        # skip initialization if it has already been performed before
        # IMPORTANT: only use this for non-critical tasks (e.g., flushing valve from GUI)
        if skip_initialization and self._is_initialized:
            return

        # try to instantiate once for nothing
        try:
            super().__init__(*args, **kwargs)
        except Exception:
            log.warning("Couldn't instantiate BPOD, retrying once...")
            time.sleep(1)
            try:
                super().__init__(*args, **kwargs)
            except (serial.serialutil.SerialException, UnicodeDecodeError) as e:
                log.error(e)
                raise serial.serialutil.SerialException(
                    "The communication with Bpod is established but the Bpod is not responsive. "
                    "This is usually indicated by the device with a green light. "
                    "Please unplug the Bpod USB cable from the computer and plug it back in to start the task. "
                ) from e
        self.default_message_idx = 0
        self.actions = Bunch({})
        self.can_control_led = self.set_status_led(True)
        self._is_initialized = True

    def close(self) -> None:
        super().close()
        self._is_initialized = False

    def __del__(self):
        with self._lock:
            if self.serial_port in Bpod._instances:
                Bpod._instances.pop(self.serial_port)

    @property
    def is_connected(self):
        return self.modules is not None

    @property
    def rotary_encoder(self):
        return self.get_module("rotary_encoder")

    @property
    def sound_card(self):
        return self.get_module("sound_card")

    def get_module(self, module: str):
        if self.modules is None:
            return None
        if module in ["re", "rotary_encoder", "RotaryEncoder"]:
            mod_name = "RotaryEncoder1"
        elif module in ["sc", "sound_card", "SoundCard"]:
            mod_name = "SoundCard1"
        mod = [x for x in self.modules if x.name == mod_name]
        if mod:
            return mod[0]
        raise ValueError(f"Module {module} not found")

    def _define_message(self, module, message):
        """
        This loads a message in the bpod interface and can then be defined as an output
        state in the state machine
        example
        >>> id_msg_bonsai_show_stim = self._define_message(self.rotary_encoder,[ord("#"), 2])
        will then be used as such in StateMachine:
        >>> output_actions=[("Serial1", id_msg_bonsai_show_stim)]
        :param message:
        :return:
        """
        if module is None:
            return
        self.load_serial_message(module, self.default_message_idx + 1, message)
        self.default_message_idx += 1
        return self.default_message_idx

    def define_xonar_sounds_actions(self):
        self.actions.update(
            {
                "play_tone": ("SoftCode", SOFTCODE.PLAY_TONE),
                "play_noise": ("SoftCode", SOFTCODE.PLAY_NOISE),
                "stop_sound": ("SoftCode", SOFTCODE.STOP_SOUND),
            }
        )

    def define_harp_sounds_actions(
        self, go_tone_index=2, noise_index=3, sound_port="Serial3"
    ):
        self.actions.update(
            {
                "play_tone": (
                    sound_port,
                    self._define_message(self.sound_card, [ord("P"), go_tone_index]),
                ),
                "play_noise": (
                    sound_port,
                    self._define_message(self.sound_card, [ord("P"), noise_index]),
                ),
                "stop_sound": (sound_port, ord("X")),
            }
        )

    def define_rotary_encoder_actions(self, re_port="Serial1"):
        """
        Each output action is a tuple with the port and the message id
        :param go_tone_index:
        :param noise_index:
        :return:
        """
        self.actions.update(
            {
                "rotary_encoder_reset": (
                    re_port,
                    self._define_message(
                        self.rotary_encoder,
                        [
                            RotaryEncoder.COM_SETZEROPOS,
                        ],
                    ),
                ),
            }
        )

    def get_ambient_sensor_reading(self):
        ambient_module = [x for x in self.modules if x.name == "AmbientModule1"][0]
        ambient_module.start_module_relay()
        self.bpod_modules.module_write(ambient_module, "R")
        reply = self.bpod_modules.module_read(ambient_module, 12)
        ambient_module.stop_module_relay()

        return {
            "Temperature_C": np.frombuffer(bytes(reply[:4]), np.float32)[0],
            "AirPressure_mb": np.frombuffer(bytes(reply[4:8]), np.float32)[0] / 100,
            "RelativeHumidity": np.frombuffer(bytes(reply[8:]), np.float32)[0],
        }

    def flush(self):
        """
        Flushes valve 1
        :return:
        """
        self.toggle_valve()

    def toggle_valve(self, duration=None):
        """
        Flushes valve 1 for duration (seconds)
        :return:
        """
        self.manual_override(self.ChannelTypes.OUTPUT, self.ChannelNames.VALVE, 1, 1)
        if duration is None:
            input("Press ENTER when done.")
        else:
            time.sleep(duration)
        self.manual_override(self.ChannelTypes.OUTPUT, self.ChannelNames.VALVE, 1, 0)

    @static_vars(supported=True)
    def set_status_led(self, state: bool) -> bool:
        if self.can_control_led and self._arcom is not None:
            try:
                log.info(f'{"en" if state else "dis"}abling Bpod Status LED')
                command = struct.pack("cB", b":", state)
                self._arcom.serial_object.write(command)
                if self._arcom.read_uint8() == 1:
                    return True
            except serial.SerialException:
                pass
            self._arcom.serial_object.reset_input_buffer()
            self._arcom.serial_object.reset_output_buffer()
            log.warning(
                "Bpod device does not support control of the status LED. Please update firmware."
            )
        return False

    def valve(self, valve_id: int, state: bool):
        self.manual_override(
            self.ChannelTypes.OUTPUT, self.ChannelNames.VALVE, valve_id, state
        )


class MyRotaryEncoder:
    def __init__(self, gain, com, connect=False):
        self.RE_PORT = com
        self.connected = False
        # How many degrees to turn forward before triggering the reward
        position_at_reward = (
            HARDWARE_SETTINGS.corridor["DISTANCE_TO_REWARD_ZONE"]
            / HARDWARE_SETTINGS.corridor["WHEEL_DIAMETER"]
            * 360
        )
        self.SET_THRESHOLDS = [
            position_at_reward,
            position_at_reward + 1,
            position_at_reward + 2,
            position_at_reward + 3,
        ]
        self.ENABLE_THRESHOLDS = [True] * len(self.SET_THRESHOLDS)
        # ENABLE_THRESHOLDS needs 8 bools even if only 2 thresholds are set
        while len(self.ENABLE_THRESHOLDS) < 8:
            self.ENABLE_THRESHOLDS.append(False)

        # The enable thresholds are in reverse order for some reason, keep an
        # eye on this if you update the encoder or the encoder firmware
        self.ENABLE_THRESHOLDS.reverse()

        # Names of the RE events generated by Bpod
        self.ENCODER_EVENTS = [
            f"RotaryEncoder1_{x}" for x in list(range(1, len(self.SET_THRESHOLDS) + 1))
        ]
        # Dict mapping threshold crossings with name ov RE event
        self.THRESHOLD_EVENTS = dict(zip(self.SET_THRESHOLDS, self.ENCODER_EVENTS))

    def set_thresholds(self) -> None:
        self.rotary_encoder.enable_thresholds(self.ENABLE_THRESHOLDS)
        self.rotary_encoder.set_thresholds(self.SET_THRESHOLDS)

    def connect(self):
        if self.RE_PORT == "COM#":
            return
        self.rotary_encoder = RotaryEncoderModule(self.RE_PORT)
        # Reading the current position doesn't work unless you do this
        self.rotary_encoder.disable_stream()
        self.rotary_encoder.set_zero_position()
        self.set_thresholds()
        self.rotary_encoder.enable_evt_transmission()
        # Disable wrapping so we don't need to count the number of turns
        self.rotary_encoder.set_wrappoint(0)
        self.connected = True

    def reset_position(self):
        # I don't know if both of these are necessary
        self.rotary_encoder.set_position(0)
        self.rotary_encoder.set_zero_position()

    def get_angle(self) -> float | None:
        return self.rotary_encoder.current_position() if self.connected else None


def sound_device_factory(output="sysdefault", samplerate=None):
    """
    Will import, configure, and return sounddevice module to play sounds using onboard sound card.
    Parameters
    ----------
    output
        defaults to "sysdefault", should be 'xonar' or 'harp'
    samplerate
        audio sample rate, defaults to 44100
    """
    if output == "xonar":
        samplerate = samplerate or 192000
        devices = sd.query_devices()
        sd.default.device = next(
            (i for i, d in enumerate(devices) if "XONAR SOUND CARD(64)" in d["name"]),
            None,
        )
        sd.default.latency = "low"
        sd.default.channels = 2
        channels = "L+TTL"
        sd.default.samplerate = samplerate
    elif output == "harp":
        samplerate = samplerate or 96000
        sd.default.samplerate = samplerate
        sd.default.channels = 2
        channels = "stereo"
    elif output == "sysdefault":
        samplerate = samplerate or 44100
        sd.default.latency = "low"
        sd.default.channels = 2
        sd.default.samplerate = samplerate
        channels = "stereo"
    else:
        raise ValueError(
            f"{output} soundcard is neither xonar, harp or sysdefault. Fix your hardware_settings.yaml"
        )
    return sd, samplerate, channels


def restart_com_port(regexp: str) -> bool:
    """
    Restart the communication port(s) matching the specified regular expression.

    Parameters
    ----------
    regexp : str
        A regular expression used to match the communication port(s).

    Returns
    -------
    bool
        Returns True if all matched ports are successfully restarted, False otherwise.

    Raises
    ------
    NotImplementedError
        If the operating system is not Windows.

    FileNotFoundError
        If the required 'pnputil.exe' executable is not found.

    Examples
    --------
    >>> restart_com_port("COM3")  # Restart the communication port with serial number 'COM3'
    True

    >>> restart_com_port("COM[1-3]")  # Restart communication ports with serial numbers 'COM1', 'COM2', 'COM3'
    True
    """
    if not os.name == "nt":
        raise NotImplementedError("Only implemented for Windows OS.")
    if not (file_pnputil := Path(shutil.which("pnputil"))).exists():
        raise FileNotFoundError("Could not find pnputil.exe")
    result = []
    for port in list_ports.grep(regexp):
        pnputil_output = subprocess.check_output(
            [file_pnputil, "/enum-devices", "/connected", "/class", "ports"]
        )
        instance_id = re.search(
            rf"(\S*{port.serial_number}\S*)", pnputil_output.decode()
        )
        if instance_id is None:
            continue
        result.append(
            subprocess.check_call(
                [file_pnputil, "/restart-device", f'"{instance_id.group}"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            == 0
        )
    return all(result)
