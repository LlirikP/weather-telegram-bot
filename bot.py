import logging
import asyncio
from main import get_weather, get_weather_data, get_coordinates_from_city, get_city_by_coord
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
import plotly.graph_objects as go
import folium
from io import BytesIO
from aiogram.fsm.state import StatesGroup, State

logging.basicConfig(level=logging.INFO)

API_TOKEN = ''

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


class WeatherForm(StatesGroup):
    start_point = State()
    end_point = State()
    days = State()
    intermediate_points = State()


@dp.message(F.text == '/start')
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Я погодный бот.\n"
        "Могу предоставить прогноз погоды для различных точек маршрута.\n"
        "Используй команду /help, чтобы узнать больше."
    )


@dp.message(F.text == '/help')
async def send_help(message: types.Message):
    await message.reply(
        "Вот список доступных команд:\n"
        "/start - Приветственное сообщение\n"
        "/help - Помощь\n"
        "/weather - Запрос прогноза погоды"
    )


@dp.message(F.text == '/weather')
async def send_weather_start(message: types.Message, state: FSMContext):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text='Отправить свою геолокацию', request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Введите начальную точку маршрута или отправьте свою геолокацию:", reply_markup=keyboard)
    await state.set_state(WeatherForm.start_point)


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


@dp.callback_query(WeatherForm.days)
async def process_days(callback_query: types.CallbackQuery, state: FSMContext):
    days = int(callback_query.data)
    await callback_query.answer()

    user_data = await state.get_data()
    start_point = user_data.get('start_point')
    end_point = user_data.get('end_point')
    start_weather_data = []
    end_weather_data = []
    try:
        start_coord = get_coordinates_from_city(start_point)
        start_weather = get_weather(start_coord[0], start_coord[1], start_coord[2], days)
        end_coord = get_coordinates_from_city(end_point)
        end_weather = get_weather(end_coord[0], end_coord[1], end_coord[2], days)
        for i in range(days):
            start_weather_data.append(get_weather_data(start_weather, i))
            end_weather_data.append(get_weather_data(end_weather, i))

    except Exception as e:
        await callback_query.message.answer(f"Ошибка при получении данных: {e}")
        await state.clear()
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(range(1, days+1)), y=[data['temperature'] for data in start_weather_data],
                             mode='lines+markers', name=f'Температура в {start_point}'))
    fig.add_trace(go.Scatter(x=list(range(1, days+1)), y=[data['temperature'] for data in end_weather_data],
                             mode='lines+markers', name=f'Температура в {end_point}'))

    fig.update_layout(title='Температурный прогноз на несколько дней',
                      xaxis_title='День',
                      yaxis_title='Температура (°C)',
                      legend_title="Города")

    img_bytes = fig.to_image(format="png")
    img_buffer = BytesIO(img_bytes)

    await callback_query.message.answer_photo(photo=img_buffer, caption="График прогноза температуры.")

    map_ = folium.Map(location=[start_coord[0], start_coord[1]], zoom_start=6)
    folium.Marker([start_coord[0], start_coord[1]], popup=start_point).add_to(map_)
    folium.Marker([end_coord[0], end_coord[1]], popup=end_point).add_to(map_)

    intermediate_points = user_data.get('intermediate_points', [])
    for point in intermediate_points:
        point_coord = get_coordinates_from_city(point)
        if point_coord:
            folium.Marker([point_coord[0], point_coord[1]], popup=point).add_to(map_)

    map_html = '/tmp/map.html'
    map_.save(map_html)

    await callback_query.message.answer("Вот карта маршрута:", reply_markup=None)
    await callback_query.message.answer_document(open(map_html, 'rb'))

    await state.clear()


@dp.message()
async def handle_unknown_message(message: types.Message):
    await message.answer('Извините, я не понял ваш запрос. Пожалуйста, выберите команду или кнопку.')


if __name__ == '__main__':
    try:
        asyncio.run(dp.start_polling(bot))
    except Exception as e:
        logging.error(f'Ошибка при запуске бота: {e}')
