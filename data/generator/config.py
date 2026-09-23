"""Shared constants, catalogues and defaults for the Zomato data generator.

Standard library only.  This module is the single source of truth for the
CSV contract (exact header lines), the canonical city / cuisine / dish
catalogues and every sampling weight used by the two CLI scripts.
"""

from __future__ import annotations

import zlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root and output directory
# ---------------------------------------------------------------------------
# data/generator/config.py -> parents[2] is the project root
# (zomato-ai-data-engineering/), NOT the current working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "raw"

TABLES = (
    "restaurants",
    "users",
    "food",
    "menu",
    "orders",
    "order_items",
    "reviews",
)

DIMENSION_TABLES = ("restaurants", "users", "food", "menu")
FACT_TABLES = ("orders", "order_items", "reviews")

# Roughly how often progress is reported (rows) and the write buffer size.
PROGRESS_INTERVAL = 1_000_000
FILE_BUFFER_BYTES = 1 << 20  # 1 MiB

# ---------------------------------------------------------------------------
# EXACT CSV headers -- the Snowflake COPY INTO contract (positional load).
#
# The four dimension files carry a leading unnamed (pandas index) column,
# so their header line starts with a comma.  The three fact files do not.
# These strings are written verbatim; do not "tidy" them.
# ---------------------------------------------------------------------------
HEADER_RESTAURANTS = (
    ",id,name,city,rating,rating_count,cost,cuisine,lic_no,link,address,menu"
)
HEADER_USERS = (
    ",user_id,name,email,password,Age,Gender,Marital Status,Occupation,"
    "Monthly Income,Educational Qualifications,Family size"
)
HEADER_FOOD = ",f_id,item,veg_or_non_veg"
HEADER_MENU = ",menu_id,r_id,f_id,cuisine,price"
HEADER_ORDERS = (
    "order_id,order_timestamp,order_date,user_id,r_id,restaurant_city,cuisine,"
    "items_count,sales_qty,subtotal,discount,delivery_fee,gst,sales_amount,"
    "currency,payment_method,order_status,customer_rating,delivery_time_min"
)
HEADER_ORDER_ITEMS = (
    "order_item_id,order_id,r_id,f_id,price,quantity,line_amount"
)
HEADER_REVIEWS = "review_id,order_id,user_id,restaurant_id,rating,comment,review_date"

HEADERS = {
    "restaurants": HEADER_RESTAURANTS,
    "users": HEADER_USERS,
    "food": HEADER_FOOD,
    "menu": HEADER_MENU,
    "orders": HEADER_ORDERS,
    "order_items": HEADER_ORDER_ITEMS,
    "reviews": HEADER_REVIEWS,
}

# ---------------------------------------------------------------------------
# Default sizes (all overridable on the CLI)
# ---------------------------------------------------------------------------
DEFAULTS = {
    "restaurants": 148_541,
    "users": 200_000,
    "food": 8_000,
    "menu_per_restaurant": 6,
    "orders": 10_000_000,
    "reviews": 300_000,
    "order_items_mean": 2.3,
    "start_date": "2024-01-01",
    "end_date": "2026-12-31",
}

# Fast smoke-test preset used by --small.
SMALL_PRESET = {
    "restaurants": 500,
    "users": 2_000,
    "food": 300,
    "menu_per_restaurant": 3,
    "orders": 20_000,
    "reviews": 2_000,
    "order_items_mean": 2.3,
    "start_date": "2024-01-01",
    "end_date": "2026-12-31",
}


def resolve_out_dir(value):
    """Resolve an --out-dir value relative to the PROJECT ROOT.

    ``None`` -> the default ``<project>/data/raw``.  Relative paths are
    joined to the project root (never the current working directory);
    absolute paths are used as given.
    """
    if value is None:
        return DEFAULT_OUT_DIR
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


# ---------------------------------------------------------------------------
# Canonical cities (weighted: Bangalore and Mumbai highest) and areas
# ---------------------------------------------------------------------------
CITIES = (
    "Bangalore",
    "Mumbai",
    "Delhi",
    "Hyderabad",
    "Chennai",
    "Pune",
    "Kolkata",
    "Ahmedabad",
    "Jaipur",
    "Lucknow",
)

CITY_WEIGHTS = (0.22, 0.20, 0.14, 0.11, 0.09, 0.08, 0.06, 0.04, 0.03, 0.03)

CITY_AREAS = {
    "Bangalore": (
        "Koramangala", "Indiranagar", "Jayanagar", "HSR Layout", "Whitefield",
        "Marathahalli", "BTM Layout", "Rajajinagar", "Malleshwaram",
        "Electronic City", "Banashankari", "Hebbal",
    ),
    "Mumbai": (
        "Andheri West", "Bandra", "Powai", "Dadar", "Lower Parel", "Juhu",
        "Colaba", "Borivali", "Thane", "Malad", "Chembur", "Vashi",
    ),
    "Delhi": (
        "Connaught Place", "Hauz Khas", "Saket", "Rajouri Garden",
        "Karol Bagh", "Dwarka", "Rohini", "Lajpat Nagar", "Pitampura",
        "Vasant Kunj", "Greater Kailash", "Chandni Chowk",
    ),
    "Hyderabad": (
        "Banjara Hills", "Jubilee Hills", "Gachibowli", "Madhapur",
        "Kukatpally", "Hitec City", "Ameerpet", "Secunderabad", "Kondapur",
        "Begumpet",
    ),
    "Chennai": (
        "T. Nagar", "Adyar", "Velachery", "Anna Nagar", "OMR",
        "Besant Nagar", "Mylapore", "Nungambakkam", "Porur", "Guindy",
    ),
    "Pune": (
        "Koregaon Park", "Baner", "Hinjewadi", "Kothrud", "Viman Nagar",
        "Aundh", "Wakad", "Kalyani Nagar", "Hadapsar", "Camp",
    ),
    "Kolkata": (
        "Park Street", "Salt Lake", "Ballygunge", "New Town", "Howrah",
        "Gariahat", "Behala", "Dum Dum", "Alipore", "Bhowanipore",
    ),
    "Ahmedabad": (
        "Navrangpura", "Satellite", "Vastrapur", "Bopal", "Maninagar",
        "Prahladnagar", "SG Highway", "Thaltej", "Gandhinagar", "Ambawadi",
    ),
    "Jaipur": (
        "Malviya Nagar", "Vaishali Nagar", "C-Scheme", "Mansarovar",
        "Tonk Road", "Raja Park", "Jagatpura", "Civil Lines",
    ),
    "Lucknow": (
        "Hazratganj", "Gomti Nagar", "Indira Nagar", "Aliganj", "Alambagh",
        "Aminabad", "Chowk", "Jankipuram",
    ),
}

# Delivered-order delivery time model per city: (base_minutes, mean_spread).
# delivery_time = clamp(int(base + expovariate(1/mean_spread)), 15, 90)
# so the p50 / p90 differ city by city (Bangalore fastest, Delhi slowest).
CITY_DELIVERY = {
    "Bangalore": (24, 8),
    "Mumbai": (28, 9),
    "Delhi": (31, 11),
    "Hyderabad": (27, 9),
    "Chennai": (29, 10),
    "Pune": (26, 8),
    "Kolkata": (31, 11),
    "Ahmedabad": (28, 9),
    "Jaipur": (29, 10),
    "Lucknow": (30, 10),
}

# ---------------------------------------------------------------------------
# Cuisines
# ---------------------------------------------------------------------------
CUISINES = (
    "North Indian",
    "Chinese",
    "South Indian",
    "Biryani",
    "Fast Food",
    "Italian",
    "Mughlai",
    "Desserts",
    "Continental",
    "Street Food",
)
CUISINE_WEIGHTS = (0.20, 0.14, 0.12, 0.13, 0.12, 0.06, 0.08, 0.05, 0.05, 0.05)

# ---------------------------------------------------------------------------
# Restaurant name building blocks
# ---------------------------------------------------------------------------
RESTAURANT_PREFIXES = (
    "Spicy", "Royal", "New", "Grand", "Hotel", "Cafe", "The", "Tasty",
    "Golden", "Green", "Annapurna", "Sagar", "Paradise", "Tandoori",
    "Urban", "Ruchi", "Delight", "Foodies", "Moti", "Bawarchi", "Nagarjuna",
    "Coastal", "Punjabi", "Dhaba", "Biryani", "Chinese", "Southern",
    "Spice", "Curry", "Tandoor", "Fusion", "Garden", "Star", "Palm",
    "Blue", "Red", "Little", "Hot", "Fresh", "Daily",
)

RESTAURANT_SUFFIXES = (
    "Kitchen", "Restaurant", "Dhaba", "Bhavan", "Corner", "Point", "Hub",
    "House", "Palace", "Diner", "Bistro", "Cafe", "Family Restaurant",
    "Express", "Junction", "Food Court", "Eatery", "Grill", "Biryani House",
    "Chinese Corner", "Garden", "Canteen", "Kitchen & Bar", "Bhojanalaya",
    "Sweets", "Bakery", "Pizzeria", "Wok", "Tiffin", "Mess", "Rasoi",
    "Cuisine", "Table", "Lounge", "Bar & Kitchen", "Snacks", "Fast Food",
    "Darbar", "Adda",
)

# ---------------------------------------------------------------------------
# Food catalogue (realistic dish names, veg flag carried by the list)
# ---------------------------------------------------------------------------
VEG_DISHES = (
    "Paneer Butter Masala", "Masala Dosa", "Veg Biryani", "Dal Makhani",
    "Palak Paneer", "Chole Bhature", "Idli Sambar", "Medu Vada",
    "Veg Hakka Noodles", "Gobi Manchurian", "Aloo Paratha", "Paneer Tikka",
    "Malai Kofta", "Rajma Chawal", "Kadai Paneer", "Veg Pulao",
    "Mysore Masala Dosa", "Rava Dosa", "Uttapam", "Pav Bhaji", "Vada Pav",
    "Samosa", "Kachori", "Dhokla", "Poha", "Upma", "Veg Fried Rice",
    "Veg Manchurian", "Mushroom Masala", "Baingan Bharta", "Bhindi Masala",
    "Aloo Gobi", "Dal Tadka", "Shahi Paneer", "Paneer Bhurji", "Matar Paneer",
    "Navratan Korma", "Veg Kolhapuri", "Veg Jalfrezi", "Malai Paneer",
    "Tandoori Roti", "Butter Naan", "Garlic Naan", "Kulcha", "Laccha Paratha",
    "Missi Roti", "Jeera Rice", "Curd Rice", "Lemon Rice", "Tomato Rice",
    "Coconut Rice", "Bisibelebath", "Pongal", "Ragi Mudde", "Akki Roti",
    "Neer Dosa", "Appam", "Puttu", "Idiyappam", "Sev Puri", "Bhel Puri",
    "Pani Puri", "Dahi Puri", "Misal Pav", "Thalipeeth", "Sabudana Khichdi",
    "Aloo Tikki", "Dahi Vada", "Khandvi", "Thepla", "Handvo", "Undhiyu",
    "Dal Baati Churma", "Gatte ki Sabzi", "Veg Momos", "Spring Rolls",
    "Honey Chilli Potato", "Crispy Corn", "Veg Cutlet", "Veg Sandwich",
    "Grilled Sandwich", "Cheese Toast", "French Fries", "Garlic Bread",
    "Cheese Garlic Bread", "Pasta Alfredo", "Pasta Arrabbiata", "Veg Pizza",
    "Margherita Pizza", "Corn Pizza", "Paneer Pizza", "Veg Burger",
    "Aloo Tikki Burger", "Paneer Wrap", "Veg Roll", "Falafel Wrap",
    "Hummus Pita", "Buddha Bowl", "Quinoa Salad", "Green Salad",
    "Fruit Salad", "Raita", "Papad", "Gulab Jamun", "Rasgulla",
    "Gajar Halwa", "Kheer", "Jalebi", "Rabri", "Kulfi", "Falooda",
    "Vanilla Ice Cream", "Chocolate Brownie", "Chocolate Cake", "Cheesecake",
    "Tiramisu", "Waffle", "Pancake", "Churros", "Mysore Pak", "Soan Papdi",
    "Rasmalai", "Peda", "Barfi", "Ladoo", "Halwa", "Shrikhand",
    "Masala Chai", "Filter Coffee", "Cold Coffee", "Mango Lassi",
    "Sweet Lassi", "Buttermilk", "Fresh Lime Soda", "Masala Lemonade",
)

NON_VEG_DISHES = (
    "Chicken Biryani", "Mutton Biryani", "Egg Biryani", "Chicken Curry",
    "Butter Chicken", "Chicken Tikka Masala", "Tandoori Chicken",
    "Chicken Tikka", "Chicken Kebab", "Seekh Kebab", "Galouti Kebab",
    "Mutton Rogan Josh", "Mutton Curry", "Keema Pav", "Chicken Chettinad",
    "Chicken 65", "Chicken Lollipop", "Chilli Chicken",
    "Chicken Manchurian", "Chicken Fried Rice", "Chicken Noodles",
    "Chicken Momos", "Fish Curry", "Fish Fry", "Fish Tikka", "Tandoori Fish",
    "Prawn Curry", "Prawn Masala", "Chilli Prawn", "Crab Masala",
    "Malvani Fish", "Goan Fish Curry", "Egg Curry", "Egg Bhurji",
    "Omelette", "Chicken Shawarma", "Chicken Wrap", "Chicken Burger",
    "Chicken Pizza", "Pepperoni Pizza", "Chicken Pasta",
    "Chicken Salami Sandwich", "Chicken Soup", "Mutton Soup",
    "Chicken Roll", "Mutton Kebab", "Pork Vindaloo", "Beef Pepper Fry",
    "Mutton Kheema", "Chicken Sausage", "Fish and Chips", "Grilled Chicken",
    "Roast Chicken", "Chicken Wings", "BBQ Chicken", "Chicken Satay",
    "Keema Naan", "Chicken Kulcha", "Mutton Keema Balls",
    "Chicken Kali Mirch", "Chicken Rara", "Mutton Nihari",
    "Chicken Stew", "Prawn Biryani", "Fish Biryani", "Egg Noodles",
    "Chicken Momo Soup", "Mutton Chaap", "Chicken Popcorn",
)

# Modifiers keep 8k generated dish names varied; "" is repeated to keep a
# good share of plain names.
FOOD_MODIFIERS = (
    "", "", "", "",
    "(Half)", "(Full)", "(Family Pack)", "(Jumbo)", "(Regular)",
    "(Special)", "(Combo)", "(Large)", "(Medium)", "(Mini)",
    "- Chef Special", "- Tandoori", "- Fried", "- Grilled", "- Spicy",
    "- Butter", "- Home Style",
)

VEG_LABELS = ("Veg", "veg", "VEG")
NON_VEG_LABELS = ("Non-Veg", "non-veg", "NON-VEG")

# ---------------------------------------------------------------------------
# Users catalogue
# ---------------------------------------------------------------------------
FIRST_NAMES = (
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh",
    "Ayaan", "Krishna", "Ishaan", "Rahul", "Rohit", "Amit", "Sandeep",
    "Vikram", "Karan", "Manish", "Nikhil", "Rajesh", "Suresh", "Anil",
    "Deepak", "Gaurav", "Harsh", "Pranav", "Siddharth", "Varun", "Yash",
    "Ananya", "Diya", "Aadhya", "Saanvi", "Pari", "Anika", "Navya",
    "Myra", "Sara", "Ira", "Kiara", "Riya", "Priya", "Neha", "Pooja",
    "Sneha", "Kavya", "Shreya", "Divya", "Meera", "Nisha", "Anjali",
    "Swati", "Rashmi", "Sunita", "Rekha", "Lakshmi", "Kiran", "Asha",
    "Farhan", "Imran", "Zoya", "Aisha", "Arnav", "Kabir", "Rishi",
)

LAST_NAMES = (
    "Sharma", "Verma", "Gupta", "Agarwal", "Bansal", "Jain", "Mehta",
    "Shah", "Patel", "Desai", "Reddy", "Rao", "Naidu", "Nair", "Menon",
    "Iyer", "Iyengar", "Krishnan", "Subramanian", "Pillai", "Chopra",
    "Kapoor", "Malhotra", "Khan", "Ansari", "Sheikh", "Syed", "Yadav",
    "Singh", "Kaur", "Gill", "Bhatia", "Sethi", "Arora", "Khanna",
    "Das", "Bose", "Banerjee", "Mukherjee", "Chatterjee", "Ghosh", "Dutta",
    "Joshi", "Deshpande", "Kulkarni", "Patil", "Jadhav", "Shinde",
    "Chauhan", "Rathore", "Thakur", "Pandey", "Mishra", "Tiwari",
    "Dubey", "Saxena", "Srivastava", "Trivedi", "Bhatt", "Naik",
)

EMAIL_DOMAINS = ("Gmail.com", "gmail.com", "Yahoo.com", "yahoo.in", "Outlook.com", "hotmail.com")

GENDERS = ("Male", "male", "M", "Female", "female", "F")
GENDER_WEIGHTS = (0.24, 0.14, 0.12, 0.24, 0.14, 0.12)

MARITAL_STATUSES = ("Single", "Married", "Divorced", "Widowed")
MARITAL_WEIGHTS = (0.42, 0.50, 0.05, 0.03)

OCCUPATIONS = (
    "Student", "Professional", "Self Employed", "Salaried", "Business",
    "Retired", "Homemaker", "Freelancer",
)
OCCUPATION_WEIGHTS = (0.16, 0.22, 0.12, 0.24, 0.10, 0.05, 0.06, 0.05)

EDUCATION_LEVELS = (
    "Graduate", "Post Graduate", "Undergraduate", "Doctorate",
    "High School", "Diploma",
)
EDUCATION_WEIGHTS = (0.36, 0.24, 0.16, 0.04, 0.12, 0.08)

INCOME_BANDS = (
    "10000", "15000", "25000", "35000", "50000", "75000", "100000",
    "No Income",
)
INCOME_WEIGHTS = (0.06, 0.10, 0.18, 0.18, 0.18, 0.12, 0.08, 0.10)

# ---------------------------------------------------------------------------
# Orders catalogue
# ---------------------------------------------------------------------------
ORDER_STATUSES = ("Delivered", "Cancelled", "Refunded")
ORDER_STATUS_WEIGHTS = (0.85, 0.08, 0.07)

PAYMENT_METHODS = (
    "Cash on Delivery", "UPI", "Credit Card", "Debit Card", "Wallet",
    "Net Banking",
)
PAYMENT_WEIGHTS = (0.34, 0.30, 0.10, 0.12, 0.09, 0.05)

DELIVERY_FEES = (0, 15, 25, 35, 49)
DELIVERY_FEE_WEIGHTS = (0.30, 0.20, 0.25, 0.15, 0.10)

QUANTITIES = (1, 2, 3, 4)
QUANTITY_WEIGHTS = (0.45, 0.30, 0.15, 0.10)

CUSTOMER_RATINGS = (1, 2, 3, 4, 5)
CUSTOMER_RATING_WEIGHTS = (0.05, 0.07, 0.13, 0.30, 0.45)

# Free-text review templates.  Sentence-shaped, never empty, and many contain
# commas so that the CSV quoting path is exercised.
NEGATIVE_COMMENTS = (
    "cold food and late delivery, very disappointing",
    "order was spilled and the packaging was torn",
    "food was stale, will not order again",
    "delivery took more than an hour and the food was cold",
    "missing items in the order, poor experience",
    "too oily and tasteless, wasted money",
    "the biryani was dry and the raita was missing",
    "worst experience, food arrived soggy and cold",
    "wrong item delivered, no response from support",
    "quantity was very less for the price, not worth it",
    "food had a weird smell, had to throw it away",
    "late delivery, rude rider, and cold food",
    "packaging leaked all over, very messy",
    "overcooked and bland, expected much better",
    "stale rotis and watery curry, highly disappointed",
    "order arrived forty minutes late and was completely cold",
    "not fresh at all, my family did not like it",
    "portion size was tiny and the gravy was cold",
    "the curry was too salty and the naan was burnt",
    "very bad taste, do not recommend this place",
)

NEUTRAL_COMMENTS = (
    "food was okay, delivery was on time",
    "decent taste but could be better, average experience",
    "packaging was fine, taste was just about average",
    "nothing special, okay for the price",
    "delivery was quick but the food was average",
    "acceptable quality, not great not bad",
    "taste was fine, portion could be bigger",
    "average food, expected a bit more flavour",
    "it was okay, might try something else next time",
    "food was warm and edible, slightly bland",
    "reasonable value for money, average taste",
    "the order was correct but the taste was ordinary",
    "decent enough for a weekday meal, nothing memorable",
    "fine experience overall, delivery was a little slow",
    "food was okay but the packaging could improve",
    "taste was passable, quantity was good",
    "not bad, but I have had better at this price",
    "delivery was smooth, food was strictly average",
    "okayish biryani, the sides were better",
    "average experience, may order again if there is an offer",
)

POSITIVE_COMMENTS = (
    "amazing food, hot and fresh, delivered quickly",
    "loved the biryani, perfectly spiced and aromatic",
    "great taste and generous portions, highly recommended",
    "delivery was super fast and the packaging was neat",
    "excellent quality, will definitely order again",
    "the paneer was soft and the gravy was delicious",
    "fantastic flavours, my whole family enjoyed it",
    "very tasty and well packed, arrived piping hot",
    "best dosa I have had in a long time, crisp and fresh",
    "food was delicious and delivery was ahead of time",
    "perfectly cooked, great value for money",
    "superb taste, the quantity was very satisfying",
    "loved every bite, the desserts were outstanding",
    "quick delivery and the food was fresh and flavourful",
    "great experience, the rider was polite and on time",
    "mouth watering food, exactly as described",
    "rich and creamy curry, really enjoyed the meal",
    "on time delivery and the food was still hot",
    "delicious food with good packaging, worth every rupee",
    "excellent taste and prompt delivery, five stars",
)

COMMENT_SUFFIXES = (
    "", "", "", "", "",
    " - would recommend to friends",
    " - thanks to the restaurant team",
    " - will order again soon",
    " - great job by the delivery partner",
)

# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------
def cumulative(weights):
    """Normalise ``weights`` into an ascending cumulative distribution."""
    total = float(sum(weights))
    acc = 0.0
    out = []
    for weight in weights:
        acc += weight / total
        out.append(acc)
    return out


def pick_index(cum, r):
    """Return the bucket index for a uniform draw ``r`` in [0, 1)."""
    for i, edge in enumerate(cum):
        if r < edge:
            return i
    return len(cum) - 1


def base_price_for(item):
    """Deterministic, process-stable base price (60-700) for a dish name.

    Uses crc32 (not the built-in ``hash``, which is salted per process) so the
    same dish always maps to the same base price across runs.
    """
    return 60 + (zlib.crc32(item.encode("utf-8")) % 641)


def build_comment(rng, rating):
    """Build a non-empty review comment whose sentiment tracks the rating."""
    if rating <= 2:
        pool = NEGATIVE_COMMENTS
    elif rating == 3:
        pool = NEUTRAL_COMMENTS
    else:
        pool = POSITIVE_COMMENTS
    return rng.choice(pool) + rng.choice(COMMENT_SUFFIXES)


def review_rating(rng):
    """~60% 4-5, ~25% 3, ~15% 1-2."""
    r = rng.random()
    if r < 0.60:
        return 5 if rng.random() < 0.55 else 4
    if r < 0.85:
        return 3
    return 2 if rng.random() < 0.50 else 1


def format_price(value):
    """Plain numeric string: ``250`` or ``349.50`` (no currency symbol)."""
    if value == int(value):
        return str(int(value))
    return "%.2f" % value
