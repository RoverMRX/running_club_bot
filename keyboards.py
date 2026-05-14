from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_kb():
    buttons = [
        [KeyboardButton(text="🏃 Создать челлендж")],
        [KeyboardButton(text="📊 Моя статистика"), KeyboardButton(text="🏆 Топ бегунов")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )