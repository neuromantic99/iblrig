from iblrig.base_choice_world import BiasedChoiceWorldSession
import iblrig.misc


class Session(BiasedChoiceWorldSession):
    pass


if __name__ == "__main__":  # pragma: no cover
    kwargs = iblrig.misc.get_task_arguments()
    sess = Session(**kwargs)
    sess.run()
