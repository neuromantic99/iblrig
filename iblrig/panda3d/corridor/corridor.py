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

NUM_TURNS_PER_LAP = 5

CORRIDOR_LENGTH = 10000
CORRIDOR_WIDTH = 25
CORRIDOR_HEIGHT = 25

CAMERA_HEIGHT = 10
# +5 so that the camera is not half out of the back wall
CAMERA_START_Y = 0


class Corridor(ShowBase):
    def __init__(self) -> None:
        ShowBase.__init__(self)
        # Panda3d has this janky logic where it pollutes the global namespace.
        # This helps pylance to not complain about it
        # probably remove in production
        base = builtins.base
        base.disableMouse()

        props = WindowProperties()
        props.setSize(800, 600)

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

        self.build_corridor(0, wall_texture, True)
        self.camera.setPos(0, CAMERA_START_Y, CAMERA_HEIGHT)
        self.camera.lookAt(0, CORRIDOR_LENGTH, CAMERA_HEIGHT)

    def clear_corridor(self) -> None:
        """Removes existing corridor nodes from the scene."""
        for node in self.corridor_nodes:
            node.removeNode()
        self.corridor_nodes.clear()

    def ITI(self) -> None:
        """Jump the camera outside the corridor for the ITI"""
        self.camera.setPos(0, CORRIDOR_LENGTH + 10, CAMERA_HEIGHT * 1000)

    def start(self) -> None:
        if not self.win:
            self.openMainWindow()

    def set_camera_position(self, fraction_through_turn: float) -> None:
        """Set camera position based on the number of
        full wheel rotations required to complete the corridor
        TODO: This logic might be slightly odd because it completely ignores
        the perimeter of the wheel
        """
        distance = (
            fraction_through_turn * CORRIDOR_LENGTH / NUM_TURNS_PER_LAP
        )  # Negative angle is forwards in the world
        self.camera.setPos(0, distance + CAMERA_START_Y, CAMERA_HEIGHT)

    def step(self) -> None:
        self.taskMgr.step()

    def moveCameraTask(self, task: Any) -> Task.cont:
        speed = 400
        dt = globalClock.getDt()  # Get the actual delta time

        if self.mouseWatcherNode.is_button_down(KeyboardButton.up()):
            self.camera.setY(self.camera, speed * dt)
        elif self.mouseWatcherNode.is_button_down(KeyboardButton.down()):
            self.camera.setY(self.camera, -speed * dt)

        return Task.cont

    def build_corridor(
        self, y_offset: int, wall_texture: str, add_back_wall: bool
    ) -> None:
        cm = CardMaker("corridor_segment")

        corridor = {}

        # Top and bottom
        cm.setFrame(
            -CORRIDOR_WIDTH / 2,
            CORRIDOR_WIDTH / 2,
            -CORRIDOR_LENGTH / 2,
            CORRIDOR_LENGTH / 2,
        )
        corridor["floor"] = self.render.attachNewNode(cm.generate())
        corridor["floor"].setPos(0, y_offset, 0)
        corridor["floor"].setP(-90)

        corridor["ceiling"] = self.render.attachNewNode(cm.generate())
        corridor["ceiling"].setPos(0, y_offset, CORRIDOR_HEIGHT)
        corridor["ceiling"].setP(-90)

        # Side Walls
        cm.setFrame(
            -CORRIDOR_LENGTH / 2,
            CORRIDOR_LENGTH / 2,
            -CORRIDOR_HEIGHT / 2,
            CORRIDOR_HEIGHT / 2,
        )

        corridor["left_wall"] = self.render.attachNewNode(cm.generate())
        corridor["left_wall"].setPos(-CORRIDOR_WIDTH / 2, y_offset, CORRIDOR_HEIGHT / 2)
        corridor["left_wall"].setH(90)

        corridor["right_wall"] = self.render.attachNewNode(cm.generate())
        corridor["right_wall"].setPos(CORRIDOR_WIDTH / 2, y_offset, CORRIDOR_HEIGHT / 2)
        corridor["right_wall"].setH(-90)

        # Front and back
        cm.setFrame(
            -CORRIDOR_WIDTH / 2,
            CORRIDOR_WIDTH / 2,
            -CORRIDOR_HEIGHT / 2,
            CORRIDOR_HEIGHT / 2,
        )

        if add_back_wall:
            corridor["back_wall"] = self.render.attachNewNode(cm.generate())
            corridor["back_wall"].setPos(
                0, CORRIDOR_LENGTH / 2 + y_offset, CORRIDOR_HEIGHT / 2
            )
            corridor["back_wall"].setH(180)

        for model_name, model in corridor.items():
            texture_path = (
                "floor.jpg"
                if model_name in ["floor", "ceiling"]
                else "endOfCorridor.png"
                if model_name == "back_wall"
                else wall_texture
            )
            texture = self.loader.load_texture(
                f"iblrig/panda3d/corridor/textures/{texture_path}"
            )

            model.setTexture(texture, 1)
            model.setTwoSided(True)
            model.reparentTo(self.render)

            num_texture_tiles = int(CORRIDOR_LENGTH / CORRIDOR_HEIGHT)

            if model_name in ["floor", "ceiling"]:
                model.setTexScale(TextureStage.getDefault(), 1, num_texture_tiles)
            elif model_name in ["left_wall", "right_wall"]:
                model.setTexScale(TextureStage.getDefault(), num_texture_tiles, 1)

            self.corridor_nodes.append(model)


if __name__ == "__main__":
    corridor = Corridor()
    corridor.run()
