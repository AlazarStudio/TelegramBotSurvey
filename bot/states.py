from aiogram.fsm.state import State, StatesGroup


class SurveyStates(StatesGroup):
    waiting_ticket = State()
    in_progress = State()


class AdminStates(StatesGroup):
    waiting_wipe_password = State()
    waiting_admin_id = State()
