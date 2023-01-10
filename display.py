import asyncio
import itertools
import os
from datetime import datetime
from typing import Literal, Optional

import pytz
import requests
from google.transit import gtfs_realtime_pb2

from PIL import Image

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
except ImportError:
    # Assume we're trying to emulate
    from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions, graphics

# Need to do an `Image.open` early, else PIL fails on "Cannot identify image file" :\
A_TRAIN_IMAGE = Image.open('./img/a_train.png').convert('RGB')

# Update every x seconds
DISPLAY_UPDATE_SECONDS = 30
SUBWAY_UPDATE_SECONDS = 60
WEATHER_UPDATE_SECONDS = 300

ROWS = 32
COLS = 64

COLOUR_YELLOW = graphics.Color(255, 255, 0)
COLOUR_LIGHT_GRAY = graphics.Color(211, 211, 211)
COLOUR_LIGHT_BLUE = graphics.Color(204, 255, 255)
COLOUR_LIGHT_ORANGE = graphics.Color(255, 229, 204)
COLOUR_GREEN = graphics.Color(64, 255, 0)

HOYT_SCHER_NORTH_STOP = "A42N"
HOYT_SCHER_SOUTH_STOP = "A42S"

EASTERN_TZ = pytz.timezone('US/Eastern')


WeatherStatus = Literal["Clouds", "Rain", "Clear", "Snow"]
Weather = tuple[int, int, int, int, Optional[WeatherStatus]]  # curr_temp, feels_like, min_temp, max_temp


class DisplayData:
    def __init__(self):
        self.subway_arrival_times: list[datetime] = []
        self.weather: Optional[Weather] = None

    def subway_arrival_deltas_minutes(self, num: int) -> list[str]:
        now = now_eastern()

        future_times = (t for t in self.subway_arrival_times if t >= now)
        delta_mins = (int((t - now).total_seconds() // 60) for t in future_times)
        return [str(t) for t in itertools.islice(delta_mins, num)]


async def loop(matrix: RGBMatrix):
    # Fire off tasks that will populate `data`
    data = DisplayData()
    asyncio.create_task(populate_subway_times(data))
    asyncio.create_task(populate_weather(data))

    # Give the initial data a good chance at being loaded on first render.
    await asyncio.sleep(2)

    # Render in the main loop
    while True:
        render(matrix, data)
        await asyncio.sleep(DISPLAY_UPDATE_SECONDS)


def render(matrix: RGBMatrix, data: DisplayData) -> bool:
    rendered_subway = rendered_weather = False
    canvas = matrix.CreateFrameCanvas()

    font = graphics.Font()
    font.LoadFont('./fonts/6x10.bdf')

    # Draw subway times
    if data.subway_arrival_times:
        arrival_minutes = data.subway_arrival_deltas_minutes(3)

        times = ",".join(arrival_minutes)

        # Draw graphic for the A train
        image = Image.open('./img/a_train.png')
        canvas.SetImage(image.convert('RGB'), offset_x=1, offset_y=1)

        # Draw subway times
        # TODO: different colours if the next train is more than 5 minutes away?
        graphics.DrawText(canvas, font, 12, 8, COLOUR_YELLOW, times)

        rendered_subway = True

    # Draw weather
    if data.weather:
        curr_temp, _, min_temp, max_temp, weather_status = data.weather

        curr_temp_str = f"{round(curr_temp)}°"
        min_temp_str = f"{round(min_temp)}°"
        max_temp_str = f"{round(max_temp)}°"

        x_offset = 12  # room for weather image

        graphics.DrawText(
            canvas,
            font,
            x_offset,
            18,
            COLOUR_LIGHT_GRAY,
            curr_temp_str,
        )

        # last number is padding between current temp and min/max
        x_offset += (len(curr_temp_str) * 5) + 6

        graphics.DrawText(
            canvas,
            font,
            x_offset,
            18,
            COLOUR_LIGHT_BLUE,
            min_temp_str,
        )

        x_offset += (len(min_temp_str) * 5) + 3

        graphics.DrawText(
            canvas,
            font,
            x_offset,
            18,
            COLOUR_LIGHT_ORANGE,
            max_temp_str,
        )

        if weather_status:
            try:
                weather_image = Image.open(f'./img/{weather_status.lower()}.png')
                canvas.SetImage(weather_image.convert('RGB'), offset_x=1, offset_y=11)
            except FileNotFoundError:
                print('No weather icon exists for', weather_status)

        rendered_weather = True

    matrix.SwapOnVSync(canvas)

    # Return a bool to indicate whether we rendered everything expected
    return rendered_subway and rendered_weather


async def populate_subway_times(data: DisplayData) -> None:
    while True:
        data.subway_arrival_times = await subway_arrival_times()
        await asyncio.sleep(SUBWAY_UPDATE_SECONDS)


async def subway_arrival_times() -> list[datetime]:
    feed = get_subway_times()
    trip_updates = [e for e in feed.entity if e.HasField('trip_update')]

    north_stops = []
    south_stops = []

    for entity in trip_updates:
        if not entity.trip_update.stop_time_update:
            continue

        for stop in entity.trip_update.stop_time_update:
            if stop.stop_id == HOYT_SCHER_NORTH_STOP:
                north_stops.append(stop)
            elif stop.stop_id == HOYT_SCHER_SOUTH_STOP:
                south_stops.append(stop)  # TODO: currently unused

    north_arrival_times = []

    for stop in north_stops:
        north_arrival_times.append(
            datetime.utcfromtimestamp(stop.arrival.time).replace(tzinfo=pytz.utc).astimezone(EASTERN_TZ)
        )

    north_arrival_times.sort()

    return north_arrival_times


def now_eastern() -> datetime:
    # MTA times do not have microsecond precision so just ignore that
    return datetime.utcnow().replace(microsecond=0, tzinfo=pytz.utc).astimezone(EASTERN_TZ)


def get_subway_times() -> gtfs_realtime_pb2.FeedMessage:
    api_key = os.getenv('MTA_API_KEY')
    assert api_key, "MTA_API_KEY not set"

    # Feed for A,C,E
    resp = requests.get(
        'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace',
        headers={'x-api-key': api_key},
    )
    resp.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)

    return feed


async def populate_weather(data: DisplayData) -> None:
    while True:
        data.weather = await get_weather()
        await asyncio.sleep(WEATHER_UPDATE_SECONDS)


async def get_weather() -> Weather:
    api_key = os.getenv('OPENWEATHER_API_KEY')
    assert api_key, "OPENWEATHER_API_KEY not set"

    resp = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"lat": "40.688986", "lon": "-73.9861586", "appid": api_key, "units": "metric"},
    )
    resp.raise_for_status()

    data = resp.json()

    # Rain
    status = None
    try:
        status = data.get('weather')[0]['main']
    except Exception:
        pass

    temp = data.get('main').get('temp')
    feels_like = data.get('main').get('feels_like')
    temp_min = data.get('main').get('temp_min')
    temp_max = data.get('main').get('temp_max')

    return (temp, feels_like, temp_min, temp_max, status)


if __name__ == '__main__':
    opts = RGBMatrixOptions()
    opts.rows = ROWS
    opts.cols = COLS
    opts.hardware_mapping = 'adafruit-hat'
    matrix = RGBMatrix(options=opts)

    try:
        asyncio.run(loop(matrix))
    except KeyboardInterrupt:
        pass
    # Ensure screen is cleared on shutdown
    matrix.Clear()
