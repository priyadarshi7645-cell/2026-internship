# Weather Data Collection Script

This project contains a Python script, [weather.py](weather.py), that downloads historical weather data for selected cities in Tamil Nadu and saves the results as a CSV file.

## Overview

The script:

- Uses the Open-Meteo Archive API
- Fetches weather data for the previous day
- Collects information for 5 major cities in Tamil Nadu:
  - Chennai
  - Madurai
  - Coimbatore
  - Tiruchirappalli
  - Sivakasi
- Filters the data to the daytime period from 6:00 AM to 5:00 PM
- Saves selected weather details into a CSV file

## What Data Is Collected

For each city and each hour in the selected time range, the script records:

- Place
- Date
- Time
- Temperature in °C
- Humidity in %
- Weather condition
- Rainfall in mm
- Wind speed in km/h
- Wind direction
- Cloud cover in %
- Surface pressure in hPa

## Script Details

The script uses the following API endpoint:

- https://archive-api.open-meteo.com/v1/archive

It requests hourly weather values including:

- temperature_2m
- relative_humidity_2m
- precipitation
- wind_speed_10m
- wind_direction_10m
- cloud_cover
- surface_pressure
- weather_code

## Requirements

Make sure you have Python installed on your system.

The script uses the Python standard library only:

- urllib
- json
- csv
- os
- datetime

No additional third-party package installation is required.

## How to Run

1. Open a terminal or command prompt.
2. Go to the project folder.
3. Run:

```bash
python weather2.py
```

## Output File

The script creates a CSV file named:

```text
yesterday_weather_12hrs.csv
```

It is saved in the same folder as the script.

## Example Output

The CSV includes rows like this:

```csv
Place,Date,Time,Temperature_C,Humidity_Percent,Weather,Rainfall_mm,Wind_Speed_kmh,Wind_Direction,Cloud_Cover_Percent,Surface_Pressure_hPa
Chennai,16 Nov 2026,06:00 AM,28.1,72,Mainly Clear,0.0,8.2,140,20,1012.4
```

## Notes

- The data is collected for the previous day automatically.
- If the API is unavailable or a network error occurs, the script prints an error message for that city.
- If the CSV file is open in Excel, the script may show a permission error and ask you to close it before running again.

## Author

This script is intended for weather data collection and basic analysis of Tamil Nadu cities.
