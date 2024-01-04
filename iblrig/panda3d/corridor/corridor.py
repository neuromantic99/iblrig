from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import KeyboardButton, TextureStage


START_POSITION = -40
END_POSITION = 59
CORRIDOR_LENGTH = END_POSITION - START_POSITION

NUM_TURNS_PER_LAP = 2


class Corridor(ShowBase):
    def __init__(self) -> None:
        ShowBase.__init__(self)
        base.disableMouse()

        # Start of the corridor
        self.camera.setPos(0, START_POSITION, 0)
        self.camera.lookAt(self.corridor)

        # Set up movement task
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
        self.camera.setPos(0, distance + START_POSITION, 0)

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

    @property
    def corridor(self):
        textures = ["checkers.jpg", "floor.jpg", "checkers.jpg", "horGrat.jpg"]

        for i in range(4):
            texture = self.loader.load_texture(
                f"iblrig/panda3d/corridor/textures/{textures[i]}"
            )
            model = self.loader.loadModel(
                f"/Users/jamesrowland/Code/iblrig/iblrig/panda3d/corridor/models/side{i+1}.obj"
            )

            model.setTexture(texture, 1)
            model.reparentTo(self.render)
            model.setPos(0, 10, 0)
            model.setH(model, 90)

            model.setTexScale(TextureStage.getDefault(), 100, 10)
            model.setTwoSided(True)
        # TODO: returns one side
        return model


if __name__ == "__main__":
    corridor = Corridor()
    corridor.run()
