# Sales Data Visualization

## Overview

This project analyzes a cleaned sales dataset using Python, pandas, Matplotlib, and Seaborn. The visualizations answer common customer and sales questions and display values directly on the charts where applicable.

The analysis is contained in `visualization.ipynb` and reads data from `final_cleaned_sales_data.csv`.

## Dataset

The dataset contains order, customer, product, payment, and sales information. Important columns used in the notebook include:

- `category`: Product category
- `total`: Sales amount
- `payment_method`: Customer payment type
- `gender`: Customer gender
- `order_date`: Date the order was placed
- `age`: Customer age
- `email`: Customer email address

## Analysis and Visualizations

### Sales by Category

Creates a bar chart showing total sales for each product category. The chart includes a rupee value above each bar and prints the highest-selling category and amount.

### Sales by Payment Method

Creates a pie chart showing the proportion of total sales contributed by each payment method. The chart displays both the sales amount and percentage for every segment.

### Customer Count by Gender

Uses a Seaborn count plot to show how many customers belong to each gender category.

### Monthly and Yearly Sales Trend

Converts `order_date` to a datetime value and groups sales by month and year.

- A line chart shows monthly sales trends.
- Monthly sales values are labeled on the chart.
- The notebook identifies the month and year with the highest sales.
- Yearly sales totals are printed in the output.

### Customer Count by Age Group

Creates age groups from the `age` column:

- Kids: 0-17
- Adults: 18-35
- Middle-aged: 36-59
- Senior Citizens: 60-100

A bar chart shows the number of customers in each age group and prints the group with the largest customer count.

### Customer Count by Email Provider

Extracts domains from the `email` column and counts customers for each provider. A bar chart shows provider usage and the notebook identifies the most commonly used provider.

## Technologies Used

- Python
- pandas
- Matplotlib
- Seaborn
- Jupyter Notebook

## Setup

Install the required Python packages:

```bash
pip install pandas matplotlib seaborn jupyter
```

Open and run the notebook:

```bash
jupyter notebook visualization.ipynb
```

Run the cells from top to bottom. The notebook expects `final_cleaned_sales_data.csv` to be in the same directory.

## Output

Running the notebook produces:

- A sales bar chart
- A payment-method pie chart
- A gender count plot
- A monthly sales line chart
- Age-group and email-provider bar charts
- Printed summaries for the highest-sales categories, months, and years