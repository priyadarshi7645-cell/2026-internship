# Day 2 Data Extraction Scripts

This project contains two Python scripts that collect market data from public sources and save the results as CSV files in the same folder.

## Project Overview

The repository focuses on extracting and transforming data for:
- Currency exchange rates against USD
- Orange commodity pricing in India

These scripts are useful for quick analysis, data collection, and exporting cleaned datasets for further exploration.

## Files

### 1. currency.py
This script fetches exchange-rate data from the Frankfurter API using USD as the base currency.

It:
- queries live exchange rate data for multiple currencies
- filters the rates for the top 15 selected countries
- maps each currency code to its country name
- saves the result to `top15_currency.csv`

Output columns:
- Date
- Country Name
- Currency
- 1 USD Value

### 2. fruit.py
This script scrapes orange commodity price data from Bajarbhav and prepares it for analysis.

It:
- fetches daily market price tables
- extracts the "Date" and "Avg modal" columns
- converts quintal-based prices into per-kg values
- fills missing dates using interpolation
- marks rows as "Actual" or "Filled"
- saves the cleaned output to `Orange_India_Filled_Rates.csv`

Output columns:
- Date
- Month
- Orange_India_Rate_Rs_Per_KG
- Data_Type

## Output Files

- `top15_currency.csv` - currency exchange data for selected countries
- `Orange_India_Filled_Rates.csv` - filled daily orange rate data for India

## Requirements

Install the required Python packages:

```bash
pip install requests pandas
```

If the HTML table extraction in `fruit.py` fails, you may also need:

```bash
pip install lxml
```

## Run the Scripts

```bash
python currency.py
python fruit.py
```

Each script saves its output CSV in the project folder.

## Notes

- `currency.py` uses a live API and depends on internet connectivity.
- `fruit.py` scrapes web data and may require slight updates if the source website changes its structure.
- The scripts are intended for small data collection and analysis tasks and can be extended for reporting or dashboard use.
