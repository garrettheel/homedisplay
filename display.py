import time
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
UPDATE_FREQ_SECONDS = 60

ROWS = 32
COLS = 64

HOYT_SCHER_NORTH_STOP = "A42N"
HOYT_SCHER_SOUTH_STOP = "A42S"

EASTERN_TZ = pytz.timezone('US/Eastern')


WeatherStatus = Literal["Clouds", "Rain", "Clear", "Snow"]
Weather = tuple[int, int, int, int, Optional[WeatherStatus]]  # curr_temp, feels_like, min_temp, max_temp


def run():
    arrival_times = subway_arrival_times()
    weather = get_weather()

    while True:
        render(arrival_times, weather)
        time.sleep(UPDATE_FREQ_SECONDS)


def subway_arrival_times() -> list[datetime]:
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

    # MTA times do not have microsecond precision so just ignore that
    now = datetime.utcnow().replace(microsecond=0, tzinfo=pytz.utc).astimezone(EASTERN_TZ)

    seconds_till_north_arrival = []
    for arrival in north_arrival_times:
        # Don't add times in the past
        if arrival > now:
            seconds_till_north_arrival.append(arrival - now)
    return seconds_till_north_arrival


def render(north_arrival_deltas: list[datetime], weather: Weather):
    opts = RGBMatrixOptions()
    opts.rows = ROWS
    opts.cols = COLS
    opts.hardware_mapping = 'adafruit-hat'
    matrix = RGBMatrix(options=opts)

    canvas = matrix.CreateFrameCanvas()
    canvas.Clear()

    yellow = graphics.Color(255, 255, 0)
    green = graphics.Color(64, 255, 0)

    font = graphics.Font()
    font.LoadFont('./fonts/6x10.bdf')

    arrival_minutes = [str(t.seconds // 60) for t in north_arrival_deltas[:3]]

    times = ",".join(arrival_minutes)

    # Draw graphic for the A train
    image = Image.open('./img/a_train.png')
    canvas.SetImage(image.convert('RGB'), offset_x=1, offset_y=1)

    # Draw subway times
    # TODO: different colours if the next train is more than 5 minutes away?
    graphics.DrawText(canvas, font, 12, 8, yellow, times)

    # Draw weather
    # TODO: different colours if it's cold/hot/raining/etc.
    curr_temp, _, min_temp, max_temp, weather_status = weather
    graphics.DrawText(canvas, font, 12, 18, green, f"{round(curr_temp)}° {round(min_temp)}-{round(max_temp)}")
    if weather_status:
        try:
            weather_status = "Clouds"
            weather_image = Image.open(f'./img/{weather_status.lower()}.png')
            canvas.SetImage(weather_image.convert('RGB'), offset_x=1, offset_y=11)
        except FileNotFoundError:
            print('No weather icon exists for', weather_status)

    matrix.SwapOnVSync(canvas)


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


def get_weather() -> Weather:
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
    run()
