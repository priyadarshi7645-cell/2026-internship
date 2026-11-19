
import requests
import pandas as pd
import re
import time

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# =====================================
# 1. WEBSITE URL
# =====================================

start_url = "https://books.toscrape.com/"

all_books = []

columns = [
    "Book_Name",
    "Category",
    "Price",
    "Rating",
    "Availability",
    "Available_Quantity"
]


# =====================================
# 2. REQUEST SESSION
# =====================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)

adapter = HTTPAdapter(max_retries=retry)

session.mount("https://", adapter)


# =====================================
# 3. PRICE FUNCTION
# =====================================

def convert_price(price_text):

    match = re.search(
        r"£\s*[\d,]+(?:\.\d{1,2})?",
        price_text
    )

    if match:
        return match.group(0).replace(" ", "")

    return price_text.strip()


# =====================================
# 4. SAVE CSV AND JSON
# =====================================

def save_files():

    df = pd.DataFrame(all_books, columns=columns)

    df.to_csv(
        "books_data.csv",
        index=False,
        encoding="utf-8-sig"
    )

    df.to_json(
        "books_data.json",
        orient="records",
        indent=4,
        force_ascii=False
    )

    return df


# =====================================
# 5. GET BOOK DETAIL INFORMATION
# =====================================

def get_book_details(book_url):

    response = session.get(
        book_url,
        timeout=(10, 20)
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


    # CATEGORY

    breadcrumb = soup.select(
        "ul.breadcrumb li"
    )

    if len(breadcrumb) >= 4:
        category = breadcrumb[-2].get_text(strip=True)
    else:
        category = "Not found"


    # PRODUCT INFORMATION

    product_info = {}

    for row in soup.select("table tr"):

        cells = row.find_all(["th", "td"])

        if len(cells) >= 2:

            key = cells[0].get_text(strip=True)

            value = cells[1].get_text(
                " ",
                strip=True
            )

            product_info[key] = value


    # PRICE INCLUDING TAX

    price_text = product_info.get(
        "Price (incl. tax)",
        ""
    )

    price = convert_price(price_text)


    # AVAILABILITY

    availability_text = product_info.get(
        "Availability",
        ""
    )


    # AVAILABLE QUANTITY

    quantity_match = re.search(
        r"\(\s*(\d+)\s+available\s*\)",
        availability_text,
        re.IGNORECASE
    )

    if quantity_match:

        quantity = int(quantity_match.group(1))

    elif "out of stock" in availability_text.lower():

        quantity = 0

    else:

        quantity = None


    # CLEAN AVAILABILITY

    availability = re.sub(
        r"\s*\(\s*\d+\s+available\s*\)",
        "",
        availability_text,
        flags=re.IGNORECASE
    ).strip()


    return {
        "Category": category,
        "Price": price,
        "Availability": availability,
        "Available_Quantity": quantity
    }


# =====================================
# 6. START WEB SCRAPING
# =====================================

url = start_url

failed_details = 0

try:

    while url:

        print("\nScraping page:", url)

        # GET LISTING PAGE

        response = session.get(
            url,
            timeout=(10, 20)
        )

        response.raise_for_status()

        # PARSE HTML

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # FIND ALL BOOKS

        books = soup.find_all(
            "article",
            class_="product_pod"
        )

        print("Books found:", len(books))


        # =================================
        # 7. EXTRACT EACH BOOK
        # =================================

        for book in books:

            # BOOK NAME

            name_tag = book.select_one("h3 a")

            if not name_tag:
                continue

            book_name = name_tag.get("title", "")


            # RATING

            rating_tag = book.select_one(
                "p.star-rating"
            )

            if rating_tag:

                rating_classes = rating_tag.get(
                    "class",
                    []
                )

                rating = (
                    rating_classes[-1]
                    if rating_classes else "Not found"
                )

            else:

                rating = "Not found"


            # BOOK DETAIL PAGE URL

            detail_url = urljoin(
                response.url,
                name_tag.get("href", "")
            )


            # GET CATEGORY, PRICE AND STOCK

            try:

                details = get_book_details(detail_url)

            except requests.exceptions.RequestException as error:

                failed_details += 1

                print(
                    "Detail page failed:",
                    book_name,
                    error
                )

                details = {
                    "Category": "Not found",
                    "Price": "Not found",
                    "Availability": "Not found",
                    "Available_Quantity": None
                }


            # STORE DATA IN DICTIONARY

            book_data = {

                "Book_Name": book_name,

                "Category": details["Category"],

                "Price": details["Price"],

                "Rating": rating,

                "Availability": details["Availability"],

                "Available_Quantity": details["Available_Quantity"]

            }

            all_books.append(book_data)


            print(
                "Collected:",
                book_name,
                "| Price:",
                details["Price"],
                "| Quantity:",
                details["Available_Quantity"]
            )


            # SMALL DELAY

            time.sleep(0.2)


        # =================================
        # 8. SAVE AFTER EACH PAGE
        # =================================

        df = save_files()

        print("Total books saved:", len(df))


        # =================================
        # 9. NEXT PAGE
        # =================================

        next_page = soup.select_one("li.next a")

        if next_page:

            next_link = next_page.get("href")

            url = urljoin(
                response.url,
                next_link
            )

        else:

            url = None


except KeyboardInterrupt:

    print("\nScraping interrupted by user.")


except requests.exceptions.RequestException as error:

    print("\nWebsite request error:", error)


finally:

    # SAVE COLLECTED DATA

    df = save_files()

    print("\n================================")
    print("SCRAPING FINISHED")
    print("================================")

    print("Total books collected:", len(df))

    print("Failed detail pages:", failed_details)

    print("\nFirst 10 records:")

    print(df.head(10))

    print("\nFiles created:")
    print("1. books_data.csv")
    print("2. books_data.json")

    session.close()
