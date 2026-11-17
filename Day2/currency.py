
import requests
import pandas as pd

# Base amount
amount = 1

# Top 15 countries and currency codes
countries = {
    "India": "INR",
    "United Kingdom": "GBP",
    "Canada": "CAD",
    "Australia": "AUD",
    "Japan": "JPY",
    "Switzerland": "CHF",
    "China": "CNY",
    "Singapore": "SGD",
    "Hong Kong": "HKD",
    "New Zealand": "NZD",
    "Sweden": "SEK",
    "Norway": "NOK",
    "Denmark": "DKK",
    "Poland": "PLN",
    "Czech Republic": "CZK"
}

# Frankfurter API
url = "https://api.frankfurter.dev/v2/rates"

params = {
    "base": "USD"
}

response = requests.get(url, params=params)
response.raise_for_status()

data = response.json()

result = []

for item in data:

    code = item["quote"]

    if code in countries.values():

        country_name = [
            country for country, currency in countries.items()
            if currency == code
        ][0]

        result.append({
            "Date": item["date"],
            "Country Name": country_name,
            "Currency": code,
            "1 USD Value": round(amount * item["rate"], 2)
        })

# Create DataFrame
df = pd.DataFrame(result)

# Arrange columns
df = df[[
    "Date",
    "Country Name",
    "Currency",
    "1 USD Value"
]]

# Save CSV
df.to_csv("top15_currency.csv", index=False)

print(df.to_string(index=False))

print("\nCSV file saved successfully!")
