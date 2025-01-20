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

# Arbitary large length backwards to stop mouse falling out the back of the corridor
ADDITIONAL_BACKWARDS_LENGTH = 1000

# Matches the aspect ratio of the screen
CORRIDOR_WIDTH = 21
CORRIDOR_HEIGHT = 17

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
CAMERA_HEIGHT = 7.5


# TODO: camera starts half out the back wall
CAMERA_START_Y = (CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH) / 2 - CORRIDOR_LENGTH


NUM_TURNS_PER_LAP = (
    HARDWARE_SETTINGS.corridor["CORRIDOR_LENGTH"]
    / HARDWARE_SETTINGS.corridor["WHEEL_CIRCUMFERENCE"]
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

        # self.taskMgr.add(self.moveCameraTask, "MoveCameraTask")

        # Keep track of corridor nodes so we can remove them later
        self.corridor_nodes: List[Any] = []

        self.texture_cache = {}

        for texture in ["horGrat.jpg", "black.png", "pebble.jpg","blackAndWhiteCircles.png", "floor.jpg", "endOfCorridor.png"]:
            self.texture_cache[texture] = self.loader.load_texture(
                f"iblrig/panda3d/corridor/textures/{texture}"
            )
            

    def start_trial(self, wall_texture: str) -> None:
        
        # If you want multiple textures in the same corridor
        # self.build_corridor(0, "blueTriangles.jpg", False)
        self.clear_corridor()  # Clear existing corridor before building a new one
        self.build_corridor(
            CORRIDOR_WIDTH,
            CORRIDOR_HEIGHT,
            CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH,
            True,
            wall_texture,
        )

        for landmark_pos in HARDWARE_SETTINGS.corridor["LANDMARK_POSITIONS"]:

            self.add_landmark(
                y_pos=CAMERA_START_Y
                + (landmark_pos / CORRIDOR_LENGTH_CM) * CORRIDOR_LENGTH,
                width=CORRIDOR_WIDTH,
                height=CORRIDOR_HEIGHT,
                length=int(
                    HARDWARE_SETTINGS.corridor["LANDMARK_WIDTH"]
                    / CORRIDOR_LENGTH_CM
                    * CORRIDOR_LENGTH
                ),
                texture_name="horGrat.jpg",
            )

        # Debugging purposes: mark the reward zone
        # self.add_landmark(
        #     y_pos=CAMERA_START_Y + (180 / CORRIDOR_LENGTH_CM) * CORRIDOR_LENGTH,
        #     width=CORRIDOR_WIDTH,
        #     height=CORRIDOR_HEIGHT,
        #     length=1,
        #     texture_name="black.png",
        # )

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
        """Build a completely black corridor"""
        self.clear_corridor()
        self.build_corridor(
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
        fraction_through_turn = position / 360
        distance = (fraction_through_turn * CORRIDOR_LENGTH) / NUM_TURNS_PER_LAP

        set_camera_position = min(
            distance + CAMERA_START_Y,
            (CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH) / 2
            - HARDWARE_SETTINGS.corridor["STOPPING_DISTANCE_FROM_END"],
        )

        self.camera.setPos(0, set_camera_position, CAMERA_HEIGHT)

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

    def add_landmark(
        self, y_pos: int, width: int, height: int, length: int, texture_name: str
    ):
        cm = CardMaker("corridor_segment")
        cm.setFrame(
            -length / 2,
            length / 2,
            -height / 2,
            height / 2,
        )

        offset_from_wall = 0.01

        left_wall = self.render.attachNewNode(cm.generate())
        left_wall.setPos(-width / 2 + offset_from_wall, y_pos, height / 2)
        left_wall.setH(90)

        right_wall = self.render.attachNewNode(cm.generate())
        right_wall.setPos(width / 2 - offset_from_wall, y_pos, height / 2)
        right_wall.setH(-90)

        cm.setFrame(
            -width / 2,
            width / 2,
            -length / 2,
            length / 2,
        )

        floor = self.render.attachNewNode(cm.generate())
        floor.setPos(0, y_pos, offset_from_wall)
        floor.setP(-90)

        ceiling = self.render.attachNewNode(cm.generate())
        ceiling.setPos(0, y_pos, height - offset_from_wall)
        ceiling.setP(-90)

        for model in [left_wall, right_wall, floor, ceiling]:
            texture = self.texture_cache[texture_name]
            model.setTexture(texture, 1)
            model.setTwoSided(True)
            model.reparentTo(self.render)
            num_texture_tiles = max(1, length // height)
            model.setTexScale(TextureStage.getDefault(), num_texture_tiles, 1)

            self.corridor_nodes.append(model)

    def build_corridor(
        self,
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
        corridor["floor"].setPos(0, 0, 0)
        corridor["floor"].setP(-90)

        corridor["ceiling"] = self.render.attachNewNode(cm.generate())
        corridor["ceiling"].setPos(0, 0, height)
        corridor["ceiling"].setP(-90)

        # Side Walls
        cm.setFrame(
            -length / 2,
            length / 2,
            -height / 2,
            height / 2,
        )

        corridor["left_wall"] = self.render.attachNewNode(cm.generate())
        corridor["left_wall"].setPos(-width / 2, 0, height / 2)
        corridor["left_wall"].setH(90)

        corridor["right_wall"] = self.render.attachNewNode(cm.generate())
        corridor["right_wall"].setPos(width / 2, 0, height / 2)
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
            corridor["back_wall"].setPos(0, length / 2, height / 2)
            corridor["back_wall"].setH(180)

        for model_name, model in corridor.items():
            texture_name = (
                floor_texture
                if model_name in ["floor", "ceiling"]
                else back_wall_texture if model_name == "back_wall" else wall_texture
            )
            texture = self.texture_cache[texture_name]

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

    wall_texture = "pebble.jpg"
    # wall_texture = "blackBars.png"

    corridor.build_corridor(
        CORRIDOR_WIDTH,
        CORRIDOR_HEIGHT,
        CORRIDOR_LENGTH + ADDITIONAL_BACKWARDS_LENGTH,
        True,
        wall_texture,
    )

    for landmark_pos in HARDWARE_SETTINGS.corridor["LANDMARK_POSITIONS"]:
        corridor.add_landmark(
            y_pos=CAMERA_START_Y
            + (landmark_pos / CORRIDOR_LENGTH_CM) * CORRIDOR_LENGTH,
            width=CORRIDOR_WIDTH,
            height=CORRIDOR_HEIGHT,
            length=int(
                HARDWARE_SETTINGS.corridor["LANDMARK_WIDTH"]
                / CORRIDOR_LENGTH_CM
                * CORRIDOR_LENGTH
            ),
            texture_name="horGrat.jpg",
        )

    corridor.run()
