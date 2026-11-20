
# Sales Data Cleaning and Exploration

## Project Overview

This project uses a Jupyter notebook to inspect and clean a sales dataset stored in `messy_sales_data.csv`. The notebook focuses on basic data-quality checks, missing-value handling, duplicate removal, and preparing a cleaned CSV.

## Project Objectives

- Load and inspect the source sales data.
- Identify missing values and duplicate rows.
- Apply the cleaning steps shown in the notebook.
- Prepare the cleaned data for further analysis.

## Dataset Description

The source file, `messy_sales_data.csv`, contains 1,000 rows and 10 columns:

| Column | Description based on the field name |
| --- | --- |
| `order_id` | Order identifier |
| `customer_name` | Customer name |
| `email` | Customer email address |
| `city` | City |
| `order_date` | Order date |
| `product` | Product |
| `quantity` | Quantity ordered |
| `unit_price` | Price per unit (currency is not specified in the notebook) |
| `payment_method` | Payment method |
| `rating` | Rating |

## Data Cleaning Steps

The notebook applies these steps:

1. Detect and remove duplicate rows with `drop_duplicates()`.
2. Remove rows missing either `customer_name` or `order_date`.
3. Fill missing `quantity` values with the column median.
4. Fill missing `unit_price` and `rating` values with their respective column means.
5. Fill missing `payment_method` and `city` values with `"Unknown"`.
6. Fill missing `email` values with `"not_provided"`; the notebook's initial missing-value check reports no missing emails.
7. Parse `order_date` using mixed-format parsing with `dayfirst=True`.
8. Trim whitespace from `city` values and convert them to title case.
9. Write the cleaned data to `cleaned_sales_data.csv` without a CSV index column.

The notebook reports zero missing values after its fill/drop steps. It does not report the final row count after cleaning.

## Python Libraries Used

- **pandas** — loading, inspecting, cleaning, and exporting tabular data.

No other libraries are imported in the notebook.

## Data Analysis

The notebook performs introductory data inspection:

- Displays the first three rows.
- Checks the dataset shape and column types.
- Computes descriptive statistics with `df.describe()`.
- Counts missing values by column.
- Counts duplicate rows.

The descriptive statistics are calculated before the cleaning steps. For the original data, the notebook reports a mean quantity of approximately `2.999`, a mean `unit_price` of approximately `11,508.73` (units/currency unspecified), and a mean rating of approximately `3.455`. It does not calculate sales revenue or compare performance across products, cities, or dates.

## Data Visualizations

The notebook does not create charts or other visualizations.

## Key Findings

- The source dataset has **1,000 rows** and **10 columns**.
- The initial missing-value counts are: `customer_name` 19, `city` 39, `order_date` 19, `quantity` 64, `unit_price` 38, `payment_method` 49, and `rating` 121. `order_id`, `email`, and `product` have no missing values in the notebook's initial check.
- **40 duplicate rows** are detected before duplicates are removed.
- Among the non-missing dates, the reported date range is **2024-01-01 to 2025-12-07**.
- The notebook documents data cleaning, but contains no charts or deeper sales-performance findings.

## How to Run the Project

1. Keep `sales_data.ipynb` and `messy_sales_data.csv` in the same folder.
2. Install pandas in the Python environment used by Jupyter:

   ```bash
   python -m pip install pandas
   ```

3. Open `sales_data.ipynb` in Jupyter or Visual Studio Code, select a Python 3 kernel, and use this folder as the working directory.
4. Before running all cells, remove the unintended leading indentation from the top-level statements that fill `payment_method` and save `cleaned_sales_data.csv`; as currently written, those indented statements may raise an `IndentationError`.
5. Run the notebook cells in order. The export cell is intended to create `cleaned_sales_data.csv` in the working directory.
