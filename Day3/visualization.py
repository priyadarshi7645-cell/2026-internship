#%% Import libraries
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

#%% Load dataset
df = pd.read_csv("cleaned_sales_data.csv")

#%% Monthly sales chart
monthly_sales = df.groupby(
    df["order_date"].dt.to_period("M")
)["total"].sum()

monthly_sales.plot(kind="line", marker="o")
plt.show()