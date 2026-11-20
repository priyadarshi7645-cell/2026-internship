# Sales Data Cleaning and Exploration

## Project Overview

This project uses a Jupyter notebook to inspect and clean the sales dataset in
`messy_sales_data.csv`. It demonstrates basic data-quality checks, missing-value
handling, duplicate removal, and exporting a cleaned CSV.

## Project Objectives

- Load and inspect the source sales data.
- Identify missing values and duplicate rows.
- Apply the cleaning steps in the notebook.
- Prepare the cleaned data for further analysis.

## Dataset

The source file contains 1,000 rows and 10 columns:

| Column | Description |
| --- | --- |
| `order_id` | Order identifier |
| `customer_name` | Customer name |
| `email` | Customer email address |
| `city` | City |
| `order_date` | Order date |
| `product` | Product |
| `quantity` | Quantity ordered |
| `unit_price` | Price per unit (currency is unspecified) |
| `payment_method` | Payment method |
| `rating` | Rating |

## Data Cleaning

The notebook:

1. Removes duplicate rows.
2. Drops rows missing `customer_name` or `order_date`.
3. Fills missing `quantity` values with the column median.
4. Fills missing `unit_price` and `rating` values with their column means.
5. Fills missing `payment_method` and `city` values with `"Unknown"`.
6. Fills missing `email` values with `"not_provided"` (none are missing in the initial check).
7. Parses `order_date` with mixed-format parsing and `dayfirst=True`.
8. Trims whitespace from `city` values and converts them to title case.
9. Writes the result to `cleaned_sales_data.csv` without a CSV index column.

## Initial Data Inspection

The notebook displays the first three rows, checks the shape and column types,
computes descriptive statistics, counts missing values, and counts duplicate
rows. These statistics are from the original dataset, before cleaning.

- Shape: 1,000 rows by 10 columns.
- Missing values: `customer_name` 19, `city` 39, `order_date` 19,
  `quantity` 64, `unit_price` 38, `payment_method` 49, and `rating` 121.
  `order_id`, `email`, and `product` have no missing values.
- Duplicate rows: 40.
- Non-missing date range: 2024-01-01 to 2025-12-07.
- Mean quantity: approximately 2.999.
- Mean `unit_price`: approximately 11,508.73 (currency unspecified).
- Mean rating: approximately 3.455.

The notebook does not calculate sales revenue, compare sales performance, or
create visualizations. It reports no final row count after cleaning.

## Requirements

- Python 3
- pandas
- Jupyter Notebook or Visual Studio Code with a Python 3 kernel

Install pandas in the environment used by Jupyter:

```bash
python -m pip install pandas
```

## How to Run

1. Keep `sales_data.ipynb` and `messy_sales_data.csv` in the same folder.
2. Open `sales_data.ipynb` in Jupyter or Visual Studio Code and select a Python 3 kernel.
3. Set the working directory to this folder.
4. Run the notebook cells in order. The final cell creates
   `cleaned_sales_data.csv` in the working directory.