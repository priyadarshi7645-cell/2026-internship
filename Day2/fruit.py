import requests
import pandas as pd
from io import StringIO

URL = "https://www.bajarbhav.in/commodities/orange/trends"

START_DATE = "2026-08-01"
END_DATE = "2026-10-31"

try:
    response = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=60
    )
    response.raise_for_status()

    tables = pd.read_html(StringIO(response.text))

    data = None

    for table in tables:
        table.columns = [
            str(c).strip().replace("\n", " ")
            for c in table.columns
        ]

        if "Date" in table.columns and "Avg modal" in table.columns:
            data = table[["Date", "Avg modal"]].copy()
            break

    if data is None:
        raise Exception("Orange price table not found")

    # Convert date
    data["Date"] = pd.to_datetime(
        data["Date"], dayfirst=True, errors="coerce"
    )

    # Convert price
    data["Quintal_Rate"] = pd.to_numeric(
        data["Avg modal"].astype(str)
        .str.replace("₹", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce"
    )

    # Quintal -> KG
    data["Rate_Per_KG"] = (data["Quintal_Rate"] / 100).round(2)

    # Remove invalid rows
    data = data.dropna(subset=["Date", "Rate_Per_KG"])

    # Remove duplicate dates (keep last)
    data = data.drop_duplicates(subset="Date", keep="last")

    # Filter Aug - Oct 2026
    data = data[
        (data["Date"] >= START_DATE) &
        (data["Date"] <= END_DATE)
    ].copy()

    # ---- FILL MISSING DATES ----
    data = data.set_index("Date").sort_index()

    full_range = pd.date_range(START_DATE, END_DATE, freq="D")
    data = data.reindex(full_range)
    data.index.name = "Date"

    # Mark which rows are missing (before filling)
    data["Data_Type"] = data["Rate_Per_KG"].isna().map(
        {True: "Filled", False: "Actual"}
    )

    # Fill missing rates by interpolation (time based)
    data["Rate_Per_KG"] = (
        data["Rate_Per_KG"]
        .interpolate(method="time", limit_direction="both")
        .round(2)
    )

    data = data.reset_index()

    # Final CSV
    final_data = pd.DataFrame({
        "Date": data["Date"].dt.strftime("%d-%m-%Y"),
        "Month": data["Date"].dt.strftime("%B"),
        "Orange_India_Rate_Rs_Per_KG": data["Rate_Per_KG"],
        "Data_Type": data["Data_Type"]
    })

    final_data.to_csv("Orange_India_Filled_Rates.csv", index=False)

    print("CSV saved successfully!")
    print(final_data.to_string(index=False))
    print("\nTotal dates:", len(final_data))
    print("Actual:", (final_data["Data_Type"] == "Actual").sum())
    print("Filled:", (final_data["Data_Type"] == "Filled").sum())

except Exception as e:
    print("Error:", e)