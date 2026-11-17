# Yesterday Weather Data Extractor

This project fetches historical weather data for selected cities in Tamil Nadu using the Open-Meteo Archive API and saves the results to a CSV file.

## Project purpose

The script `weather2.py` collects weather information from the previous day for the following cities:

- Chennai
- Madurai
- Coimbatore
- Tiruchirappalli
- Sivakasi

It pulls hourly weather data for the period from 6:00 AM to 5:00 PM and stores it as a daily dataset for analysis.

## Data source

The application uses:

- Open-Meteo Archive API
- Historical weather records for the previous date
- Timezone: Asia/Kolkata

## What the script does

- Fetches weather data for each city using latitude and longitude
- Extracts weather information for each hour between 6:00 AM and 5:00 PM
- Converts weather codes into readable descriptions
- Collects details such as:
  - temperature
  - humidity
  - rainfall
  - wind speed
  - wind direction
  - cloud cover
  - surface pressure
- Saves the final dataset into a CSV file named `yesterday_weather_12hrs.csv`

## Output file

The generated CSV contains the following columns:

- Place
- Date
- Time
- Temperature_C
- Humidity_Percent
- Weather
- Rainfall_mm
- Wind_Speed_kmh
- Wind_Direction
- Cloud_Cover_Percent
- Surface_Pressure_hPa

## Requirements

This script uses the Python standard library only:

- `urllib.request`
- `urllib.parse`
- `json`
- `csv`
- `os`
- `datetime`

No extra packages are required.

## Run the project

From the project folder, run:

```bash
python weather2.py
```

The script will create the CSV file in the same directory as the Python script.

## Notes

- The API returns data for the previous calendar date automatically.
- If the CSV file is open in Excel, the script may prompt you to close it before overwriting.
- The weather code mapping is included to convert numeric codes into readable weather conditions.
