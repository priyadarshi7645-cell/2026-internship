
import urllib.request
import urllib.parse
import json
import csv
import os
from datetime import datetime, timedelta

# Historical Weather API
API_URL = "https://archive-api.open-meteo.com/v1/archive"

# Tamil Nadu Places
places = {
    "Chennai": (13.0827, 80.2707),
    "Madurai": (9.9252, 78.1198),
    "Coimbatore": (11.0168, 76.9558),
    "Tiruchirappalli": (10.7905, 78.7047),
    "Sivakasi": (9.4533, 77.8024)
}

# Yesterday's date
yesterday = datetime.now() - timedelta(days=1)
date_value = yesterday.strftime("%Y-%m-%d")
display_date = yesterday.strftime("%d %b %Y")

weather_records = []

# Weather code conversion
def get_weather_description(code):

    weather_types = {
        0: "Clear Sky",
        1: "Mainly Clear",
        2: "Partly Cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Rime Fog",
        51: "Light Drizzle",
        53: "Moderate Drizzle",
        55: "Dense Drizzle",
        61: "Slight Rain",
        63: "Moderate Rain",
        65: "Heavy Rain",
        71: "Slight Snow",
        80: "Rain Showers",
        81: "Moderate Rain Showers",
        82: "Heavy Rain Showers",
        95: "Thunderstorm",
        96: "Thunderstorm with Hail",
        99: "Heavy Thunderstorm with Hail"
    }

    return weather_types.get(code, "Unknown")


# Fetch data
for city, (latitude, longitude) in places.items():

    print("Fetching:", city)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": date_value,
        "end_date": date_value,
        "hourly": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "precipitation,"
            "wind_speed_10m,"
            "wind_direction_10m,"
            "cloud_cover,"
            "surface_pressure,"
            "weather_code"
        ),
        "timezone": "Asia/Kolkata"
    }

    try:
        query = urllib.parse.urlencode(params)
        url = API_URL + "?" + query

        request = urllib.request.Request(url)

        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        hourly = data["hourly"]

        for i, time_value in enumerate(hourly["time"]):

            record_time = datetime.strptime(
                time_value, "%Y-%m-%dT%H:%M"
            )

            # 6 AM to 5 PM = 12 hours
            if 6 <= record_time.hour <= 17:

                code = hourly["weather_code"][i]

                weather_records.append({
                    "Place": city,
                    "Date": display_date,
                    "Time": record_time.strftime("%I:%M %p"),
                    "Temperature_C": hourly["temperature_2m"][i],
                    "Humidity_Percent": hourly["relative_humidity_2m"][i],
                    "Weather": get_weather_description(code),
                    "Rainfall_mm": hourly["precipitation"][i],
                    "Wind_Speed_kmh": hourly["wind_speed_10m"][i],
                    "Wind_Direction": hourly["wind_direction_10m"][i],
                    "Cloud_Cover_Percent": hourly["cloud_cover"][i],
                    "Surface_Pressure_hPa": hourly["surface_pressure"][i]
                })

        print("Completed:", city)

    except Exception as error:
        print("API Error:", city, error)


# CSV file save location
folder = os.path.dirname(os.path.abspath(__file__))
filename = os.path.join(folder, "yesterday_weather_12hrs.csv")

fieldnames = [
    "Place",
    "Date",
    "Time",
    "Temperature_C",
    "Humidity_Percent",
    "Weather",
    "Rainfall_mm",
    "Wind_Speed_kmh",
    "Wind_Direction",
    "Cloud_Cover_Percent",
    "Surface_Pressure_hPa"
]

try:
    with open(filename, "w", newline="", encoding="utf-8-sig") as file:

        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(weather_records)

    print("\nCSV FILE SAVED SUCCESSFULLY!")
    print("Date:", display_date)
    print("Total Records:", len(weather_records))
    print("File Location:", filename)

except PermissionError:
    print("Please close the CSV file in Excel and run again.")

except OSError as error:
    print("File Saving Error:", error)

print("\nProgram Completed!")
