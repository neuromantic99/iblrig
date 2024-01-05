import builtins

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import (
    CardMaker,
    KeyboardButton,
    WindowProperties,
)

NUM_TURNS_PER_LAP = 2

CORRIDOR_LENGTH = 200
CORRIDOR_WIDTH = 40
CORRIDOR_HEIGHT = 10

CAMERA_HEIGHT = 5
# +1 so that the camera is not half out of the back wall
CAMERA_START_Y = -CORRIDOR_LENGTH / 2 + 1


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

        self.build_corridor()

        self.left_window = self.openWindow(props, makeCamera=0)
        self.right_window = self.openWindow(props, makeCamera=0)

        self.camera_left = self.makeCamera(self.left_window)
        self.camera_right = self.makeCamera(self.right_window)

        # Yolks the cameras together
        self.camera_left.reparentTo(self.camera)
        self.camera_right.reparentTo(self.camera)

        self.camera.setPos(0, CAMERA_START_Y, CAMERA_HEIGHT)
        self.camera.lookAt(0, CORRIDOR_LENGTH, CAMERA_HEIGHT)

        self.camera_left.setHpr(90, 0, 0)
        self.camera_right.setHpr(-90, 0, 0)

        self.taskMgr.add(self.moveCameraTask, "MoveCameraTask")

    def start(self):
        if not self.win:
            self.openMainWindow()

    def set_camera_position(self, fraction_through_turn: float):
        """Set camera position based on the number of
        full wheel rotations required to complete the corridor
        TODO: This logic might be slightly odd because it completely ignores
        the perimeter of the wheel
        """
        distance = fraction_through_turn * CORRIDOR_LENGTH / NUM_TURNS_PER_LAP
        self.camera.setPos(0, distance + CAMERA_START_Y, CAMERA_HEIGHT)

    def step(self):
        self.taskMgr.step()

    def moveCameraTask(self, task):
        speed = 10
        dt = globalClock.getDt()  # Get the actual delta time

        if self.mouseWatcherNode.is_button_down(KeyboardButton.up()):
            self.camera.setY(self.camera, speed * dt)
        elif self.mouseWatcherNode.is_button_down(KeyboardButton.down()):
            self.camera.setY(self.camera, -speed * dt)

        return Task.cont

    def build_corridor(self):
        cm = CardMaker("corridor_segment")
        textures = ["checkers.jpg", "floor.jpg", "checkers.jpg", "horGrat.jpg"]

        # Top and bottom
        cm.setFrame(
            -CORRIDOR_WIDTH / 2,
            CORRIDOR_WIDTH / 2,
            -CORRIDOR_LENGTH / 2,
            CORRIDOR_LENGTH / 2,
        )
        floor = self.render.attachNewNode(cm.generate())
        floor.setPos(0, 0, 0)
        floor.setP(-90)
        floor.setTwoSided(True)

        ceiling = self.render.attachNewNode(cm.generate())
        ceiling.setPos(0, 0, CORRIDOR_HEIGHT)
        ceiling.setP(-90)
        ceiling.setTwoSided(True)

        # Side Walls
        cm.setFrame(
            -CORRIDOR_LENGTH / 2,
            CORRIDOR_LENGTH / 2,
            -CORRIDOR_HEIGHT / 2,
            CORRIDOR_HEIGHT / 2,
        )

        left_wall = self.render.attachNewNode(cm.generate())
        left_wall.setPos(-CORRIDOR_WIDTH / 2, 0, CORRIDOR_HEIGHT / 2)
        left_wall.setH(90)
        left_wall.setTwoSided(True)

        right_wall = self.render.attachNewNode(cm.generate())
        right_wall.setPos(CORRIDOR_WIDTH / 2, 0, CORRIDOR_HEIGHT / 2)
        right_wall.setH(-90)
        right_wall.setTwoSided(True)

        # Front and back
        cm.setFrame(
            -CORRIDOR_WIDTH / 2,
            CORRIDOR_WIDTH / 2,
            -CORRIDOR_HEIGHT / 2,
            CORRIDOR_HEIGHT / 2,
        )

        front_wall = self.render.attachNewNode(cm.generate())
        front_wall.setPos(0, CORRIDOR_LENGTH / 2, CORRIDOR_HEIGHT / 2)
        front_wall.setH(180)
        front_wall.setTwoSided(True)

        back_wall = self.render.attachNewNode(cm.generate())
        back_wall.setPos(0, -CORRIDOR_LENGTH / 2, CORRIDOR_HEIGHT / 2)
        back_wall.setTwoSided(True)

        for idx, model in enumerate(
            [ceiling, floor, left_wall, right_wall, front_wall, back_wall]
        ):
            texture = self.loader.load_texture(
                f"iblrig/panda3d/corridor/textures/{textures[idx % 4]}"
            )

            model.setTexture(texture, 1)
            model.reparentTo(self.render)

            # model.setTexScale(TextureStage.getDefault(), 100, 10)


if __name__ == "__main__":
    corridor = Corridor()
    corridor.run()
