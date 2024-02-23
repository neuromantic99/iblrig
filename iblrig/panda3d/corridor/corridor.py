import builtins
from typing import Any, List

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import (
    CardMaker,
    KeyboardButton,
    WindowProperties,
    TextureStage,
)

import iblrig.path_helper


HARDWARE_SETTINGS = iblrig.path_helper.load_settings_yaml("hardware_settings.yaml")

DISTANCE_TO_REWARD_ZONE = HARDWARE_SETTINGS.corridor["DISTANCE_TO_REWARD_ZONE"]

CORRIDOR_LENGTH_CM = HARDWARE_SETTINGS.corridor["CORRIDOR_LENGTH"]

# Arbitary length backwards to stop mouse falling out the back of the corridor
ADDITIONAL_BACKWARDS_LENGTH = 1000

# End of the corridor is the same size as the field of view
CORRIDOR_WIDTH = CORRIDOR_HEIGHT = 10

# A screen is 1 unit. So the corridor in units should be it's length in cm / the screen width
NUMBER_OF_SCREENS_IN_CORRIDOR = (
    CORRIDOR_LENGTH_CM / HARDWARE_SETTINGS.screen["SCREEN_WIDTH"]
)

ASPECT_RATIO = (
    HARDWARE_SETTINGS.screen["SCREEN_WIDTH_PX"]
    / HARDWARE_SETTINGS.screen["SCREEN_HEIGHT_PX"]
)

# because the screen is wider than it is high, we need to compensate for this with the
# length. Also need to multiply by the width to make the width 1 unit
CORRIDOR_LENGTH = NUMBER_OF_SCREENS_IN_CORRIDOR * ASPECT_RATIO * CORRIDOR_WIDTH

# Scale the actual screen that's rendered by a factor of two so you can drag it
SCREEN_WIDTH_PX = int(HARDWARE_SETTINGS.screen["SCREEN_WIDTH_PX"] / 2)
SCREEN_HEIGHT_PX = int(HARDWARE_SETTINGS.screen["SCREEN_HEIGHT_PX"] / 2)

# Think about this
CAMERA_HEIGHT = 1

# TODO: Currently the camera stops moving an arbitary distance from the end to simulate
# collision logic. Can be handled with panda collision logic but this is quite complex
STOPPING_DISTANCE_FROM_END = 5

# TODO: camera starts half out the back wall
CAMERA_START_Y = (CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH) / 2 - CORRIDOR_LENGTH


NUM_TURNS_PER_LAP = (
    HARDWARE_SETTINGS.corridor["CORRIDOR_LENGTH"]
    / HARDWARE_SETTINGS.corridor["WHEEL_DIAMETER"]
)


class Corridor(ShowBase):
    def __init__(self) -> None:
        ShowBase.__init__(self)
        # self.render.set_scale(HARDWARE_SETTINGS.corridor["SCREEN_WIDTH"] / SCREEN_WIDTH)

        props = WindowProperties()
        props.setSize(SCREEN_WIDTH_PX, SCREEN_HEIGHT_PX)

        self.win.requestProperties(props)

        # Panda3d has this janky logic where it pollutes the global namespace.
        # So this is actually defined
        base.disableMouse()

        self.left_window = self.openWindow(props, makeCamera=0)
        self.right_window = self.openWindow(props, makeCamera=0)

        self.camera_left = self.makeCamera(self.left_window)
        self.camera_right = self.makeCamera(self.right_window)

        # Yolks the cameras together
        self.camera_left.reparentTo(self.camera)
        self.camera_right.reparentTo(self.camera)

        self.camera_left.setHpr(90, 0, 0)
        self.camera_right.setHpr(-90, 0, 0)

        self.taskMgr.add(self.moveCameraTask, "MoveCameraTask")

        # Keep track of corridor nodes so we can remove them later
        self.corridor_nodes: List[Any] = []

    def start_trial(self, wall_texture: str) -> None:
        # If you want multiple textures in the same corridor
        # self.build_corridor(0, "blueTriangles.jpg", False)
        self.clear_corridor()  # Clear existing corridor before building a new one
        self.build_corridor(
            0,
            CORRIDOR_WIDTH,
            CORRIDOR_HEIGHT,
            CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH,
            False,
            wall_texture,
        )

        self.camera.setPos(0, CAMERA_START_Y, CAMERA_HEIGHT)
        self.camera.lookAt(
            0, CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH, CAMERA_HEIGHT
        )

    def clear_corridor(self) -> None:
        """Removes existing corridor nodes from the scene."""
        for node in self.corridor_nodes:
            node.removeNode()
        self.corridor_nodes.clear()

    def ITI(self) -> None:
        """Jump the camera outside the corridor for the ITI"""
        self.clear_corridor()
        self.build_corridor(
            0,
            CORRIDOR_WIDTH,
            CORRIDOR_HEIGHT,
            CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH,
            True,
            "black.png",
            "black.png",
            "black.png",
        )
        self.step()

    def start(self) -> None:
        if not self.win:
            self.openMainWindow()

    def set_camera_position(self, position: float) -> None:
        """Set camera position based on the number of
        full wheel rotations required to complete the corridor
        """
        print(f"possy: {position}")
        fraction_through_turn = position / 360
        distance = (fraction_through_turn * CORRIDOR_LENGTH) / NUM_TURNS_PER_LAP

        set_camera_position = min(
            distance + CAMERA_START_Y,
            (CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH) / 2
            - STOPPING_DISTANCE_FROM_END,
        )

        print(f"camera pos {set_camera_position}")
        self.camera.setPos(3.5, set_camera_position, CAMERA_HEIGHT)

    def step(self) -> None:
        self.taskMgr.step()

    def moveCameraTask(self, task: Any) -> Task.cont:
        speed = 10
        dt = globalClock.getDt()  # Get the actual delta time

        if self.mouseWatcherNode.is_button_down(KeyboardButton.up()):
            self.camera.setY(self.camera, speed * dt)
        elif self.mouseWatcherNode.is_button_down(KeyboardButton.down()):
            self.camera.setY(self.camera, -speed * dt)

        return Task.cont

    def build_corridor(
        self,
        y_offset: int,
        width: int,
        height: int,
        length: int,
        add_back_wall: bool,
        wall_texture: str,
        floor_texture: str = "floor.jpg",
        back_wall_texture: str = "endOfCorridor.png",
    ) -> None:
        cm = CardMaker("corridor_segment")

        corridor = {}

        # Top and bottom
        cm.setFrame(
            -width / 2,
            width / 2,
            -length / 2,
            length / 2,
        )
        corridor["floor"] = self.render.attachNewNode(cm.generate())
        corridor["floor"].setPos(0, y_offset, 0)
        corridor["floor"].setP(-90)

        corridor["ceiling"] = self.render.attachNewNode(cm.generate())
        corridor["ceiling"].setPos(0, y_offset, height)
        corridor["ceiling"].setP(-90)

        # Side Walls
        cm.setFrame(
            -length / 2,
            length / 2,
            -height / 2,
            height / 2,
        )

        corridor["left_wall"] = self.render.attachNewNode(cm.generate())
        corridor["left_wall"].setPos(-width / 2, y_offset, height / 2)
        corridor["left_wall"].setH(90)

        corridor["right_wall"] = self.render.attachNewNode(cm.generate())
        corridor["right_wall"].setPos(width / 2, y_offset, height / 2)
        corridor["right_wall"].setH(-90)

        # Front and back
        cm.setFrame(
            -width / 2,
            width / 2,
            -height / 2,
            height / 2,
        )

        if add_back_wall:
            corridor["back_wall"] = self.render.attachNewNode(cm.generate())
            corridor["back_wall"].setPos(0, length / 2 + y_offset, height / 2)
            corridor["back_wall"].setH(180)

        for model_name, model in corridor.items():
            texture_path = (
                floor_texture
                if model_name in ["floor", "ceiling"]
                else back_wall_texture if model_name == "back_wall" else wall_texture
            )
            texture = self.loader.load_texture(
                f"iblrig/panda3d/corridor/textures/{texture_path}"
            )

            model.setTexture(texture, 1)
            model.setTwoSided(True)
            model.reparentTo(self.render)

            num_texture_tiles = int(length / height)

            if model_name in ["floor", "ceiling"]:
                model.setTexScale(TextureStage.getDefault(), 1, num_texture_tiles)
            elif model_name in ["left_wall", "right_wall"]:
                model.setTexScale(TextureStage.getDefault(), num_texture_tiles, 1)

            self.corridor_nodes.append(model)


if __name__ == "__main__":
    corridor = Corridor()
    corridor.set_camera_position(10)

    corridor.build_corridor(
        0,
        CORRIDOR_WIDTH,
        CORRIDOR_HEIGHT,
        CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH,
        True,
        "blueTriangles.jpg",
        "blueTriangles.jpg",
        "black.png",
    )
    corridor.run()
