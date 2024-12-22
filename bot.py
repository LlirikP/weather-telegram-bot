import logging
import asyncio
from main import get_weather, get_weather_data, get_coordinates_from_city, get_city_by_coord
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

logging.basicConfig(level=logging.INFO)

API_TOKEN = ''

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


# Определение состояний формы для обработки ввода пользователя
class WeatherForm(StatesGroup):
    start_point = State()
    end_point = State()
    days = State()
    intermediate_points = State()


# Команда /start: приветственное сообщение для пользователя
@dp.message(F.text == '/start')
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Я погодный бот.\n"
        "Могу предоставить прогноз погоды для различных точек маршрута.\n"
        "Используй команду /help, чтобы узнать больше."
    )


# Команда /help: описание доступных команд
@dp.message(F.text == '/help')
async def send_help(message: types.Message):
    await message.reply(
        "Вот список доступных команд:\n"
        "/start - Приветственное сообщение\n"
        "/help - Помощь\n"
        "/weather - Запрос прогноза погоды"
    )


# Команда /weather: начало запроса прогноза погоды
@dp.message(F.text == '/weather')
async def send_weather_start(message: types.Message, state: FSMContext):
    # Предложение отправить геолокацию или ввести город
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text='Отправить свою геолокацию', request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Введите начальную точку маршрута или отправьте свою геолокацию:", reply_markup=keyboard)
    await state.set_state(WeatherForm.start_point)


# Обработка текстового ввода начальной точки маршрута
@dp.message(WeatherForm.start_point, F.content_type == "text")
async def start_point_text(message: types.Message, state: FSMContext):
    start_point = message.text.strip()
    start_city = get_coordinates_from_city(start_point)

    if not start_city:
        await message.answer("Не удалось определить начальную точку. Попробуйте снова.")
        return

    await state.update_data(start_point=start_point)
    await state.set_state(WeatherForm.end_point)
    await message.answer("Введите конечную точку маршрута:")


# Обработка геолокации для начальной точки маршрута
@dp.message(WeatherForm.start_point, F.content_type == "location")
async def start_point_location(message: types.Message, state: FSMContext):
    latitude = message.location.latitude
    longitude = message.location.longitude
    start_key = get_city_by_coord(latitude, longitude)
    start_point = "Ваше текущее местоположение"

    if not start_key:
        await message.answer("Не удалось определить начальную точку. Попробуйте снова.")
        return

    await state.update_data(start_point=start_point, start_key=start_key)
    await message.answer("Введите конечную точку маршрута:")
    await state.set_state(WeatherForm.end_point)


# Обработка ввода конечной точки маршрута
@dp.message(WeatherForm.end_point)
async def end_point_text(message: types.Message, state: FSMContext):
    end_point = message.text.strip()
    end_city = get_coordinates_from_city(end_point)

    if not end_city:
        await message.answer("Не удалось определить конечную точку. Попробуйте снова.")
        return

    await state.update_data(end_point=end_point)

    await state.set_state(WeatherForm.intermediate_points)
    await message.answer("Введите промежуточные города через запятую, если они есть. Если нет, просто отправьте 'Нет'.")


# Обработка ввода промежуточных точек маршрута
@dp.message(WeatherForm.intermediate_points)
async def intermediate_points_text(message: types.Message, state: FSMContext):
    intermediate_points = message.text.strip()

    if intermediate_points.lower() != 'нет':
        intermediate_points = [point.strip() for point in intermediate_points.split(',')]
    else:
        intermediate_points = []

    await state.update_data(intermediate_points=intermediate_points)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Прогноз на 1 день', callback_data='1')],
        [InlineKeyboardButton(text='Прогноз на 5 дней', callback_data='5')],
    ])
    await message.answer("Выберите временной интервал прогноза:", reply_markup=keyboard)
    await state.set_state(WeatherForm.days)


# Обработка выбора временного интервала прогноза
@dp.callback_query(WeatherForm.days)
async def process_days(callback_query: types.CallbackQuery, state: FSMContext):
    days = int(callback_query.data)
    await callback_query.answer()

    if days == 1:
        await callback_query.message.answer(f"Получаем прогноз на {days} день...")
    else:
        await callback_query.message.answer(f"Получаем прогноз на {days} дней...")

    user_data = await state.get_data()
    start_point = user_data.get('start_point')
    end_point = user_data.get('end_point')
    intermediate_points = user_data.get('intermediate_points', [])

    all_points = [start_point] + intermediate_points + [end_point]

    forecast_data = {}

    try:
        # Получаем прогноз для каждой точки маршрута
        for point in all_points:
            coord = get_coordinates_from_city(point)
            if coord:
                weather = get_weather(coord[0], coord[1], coord[2], days)
                forecast_data[point] = []
                for i in range(days):
                    forecast_data[point].append(get_weather_data(weather, i))
    except Exception as e:
        await callback_query.message.answer(f"Ошибка при получении данных: {e}")
        await state.clear()
        return

    # Формируем ответ с прогнозом для каждой точки маршрута
    response = ""
    for point in all_points:
        response += f"\nПрогноз для {point}:\n"
        for i in range(days):
            response += f"День {i + 1}\n"
            for key, value in forecast_data[point][i].items():
                response += f"{key}: {value}\n"

    await callback_query.message.answer(response)
    await state.clear()


# Обработка неизвестных сообщений
@dp.message()
async def handle_unknown_message(message: types.Message):
    await message.answer('Извините, я не понял ваш запрос. Пожалуйста, выберите команду или кнопку.')


if __name__ == '__main__':
    try:
        # Запуск бота с использованием асинхронного метода
        asyncio.run(dp.start_polling(bot))
    except Exception as e:
        logging.error(f'Ошибка при запуске бота: {e}')
