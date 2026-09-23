#!/usr/bin/env python3
"""Generate the three clean Zomato fact CSVs.

Produces, under ``<out-dir>/<table>/<table>.csv``:

    orders, order_items, reviews

Reads the already-generated dimensions from the same ``--out-dir``
(``restaurants.csv``, ``users.csv``, ``food.csv`` and, when present,
``menu.csv``) and preserves referential integrity for every key.

The run is a single streaming pass: nothing is accumulated in memory and
files are written through a buffered ``csv.writer`` with an explicit
``lineterminator="\\n"`` (Snowflake's default RECORD_DELIMITER).  Timestamps
are strictly increasing with ``order_id`` so incremental dbt watermarks work.

Run directly (no package install required)::

    python3 data/generator/generate_facts.py --small
    python3 data/generator/generate_facts.py --orders 10000000 --reviews 300000
"""

from __future__ import annotations

import argparse
import array
import csv
import math
import random
import sys
import time
from datetime import date
from pathlib import Path

try:  # normal package import (python -m data.generator.generate_facts)
    from . import config
except ImportError:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config

_EPOCH = date(1970, 1, 1)


# ---------------------------------------------------------------------------
# CSV plumbing
# ---------------------------------------------------------------------------
def open_output(path, header):
    """Open ``path`` for writing and emit the exact header line.

    ``newline=""`` on open() AND ``lineterminator="\\n"`` on the writer keep
    ``\\r`` out of the files, which is required by Snowflake's default
    RECORD_DELIMITER of ``\\n``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(
        path, "w", encoding="utf-8", newline="", buffering=config.FILE_BUFFER_BYTES
    )
    handle.write(header + "\n")
    writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    return handle, writer


def _progress(label, done, total):
    if done % config.PROGRESS_INTERVAL == 0:
        sys.stderr.write(
            "[%s] %s / %s rows\n" % (label, format(done, ","), format(total, ","))
        )
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# Dimension loading (only the small columns needed are kept in memory)
# ---------------------------------------------------------------------------
def _iter_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # skip the header row
        for row in reader:
            yield row


def _as_int(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def load_restaurants(path):
    """Return (r_ids, cities, cuisines) -- all parallel lists."""
    ids, cities, cuisines = [], [], []
    for row in _iter_rows(path):
        if len(row) < 8:
            continue
        r_id = _as_int(row[1])
        if r_id is None:
            continue
        ids.append(r_id)
        cities.append((row[3] or "").strip() or "Unknown, Unknown")
        cuisines.append((row[7] or "").strip() or "North Indian")
    return ids, cities, cuisines


def load_users(path):
    ids = []
    for row in _iter_rows(path):
        if len(row) < 2:
            continue
        user_id = _as_int(row[1])
        if user_id is not None:
            ids.append(user_id)
    return ids


def load_food(path):
    f_ids, items = [], []
    for row in _iter_rows(path):
        if len(row) < 3:
            continue
        f_id = (row[1] or "").strip()
        if not f_id:
            continue
        f_ids.append(f_id)
        items.append((row[2] or "").strip() or "Assorted Dish")
    return f_ids, items


def load_menu(path, food_index):
    """Optional: map r_id -> array('i') of food indexes from menu.csv.

    Returns None when menu.csv is absent.  A compact per-restaurant array
    keeps ~891k menu rows memory-light while letting order items come from
    the restaurant's actual menu.
    """
    if not path.exists():
        return None
    menu = {}
    for row in _iter_rows(path):
        if len(row) < 5:
            continue
        r_id = _as_int(row[2])
        food_idx = food_index.get((row[3] or "").strip())
        if r_id is None or food_idx is None:
            continue
        bucket = menu.get(r_id)
        if bucket is None:
            bucket = array.array("i")
            menu[r_id] = bucket
        bucket.append(food_idx)
    return menu


# ---------------------------------------------------------------------------
# Review sampling (Floyd's algorithm: uniform k-subset, O(k), bounded memory)
# ---------------------------------------------------------------------------
def sample_order_offsets(rng, n_orders, k):
    """Return a set of 0-based order offsets to attach reviews to."""
    if k <= 0:
        return set()
    if k >= n_orders:
        return set(range(n_orders))
    chosen = set()
    for j in range(n_orders - k, n_orders):
        t = rng.randrange(j + 1)
        if t in chosen:
            chosen.add(j)
        else:
            chosen.add(t)
    return chosen


# ---------------------------------------------------------------------------
# Main streaming generation
# ---------------------------------------------------------------------------
def write_facts(out_dir, restaurants, users, food, menu, n_orders, n_reviews,
                order_items_mean, start_date, end_date, seed):
    r_ids, r_cities, r_cuisines = restaurants
    user_ids = users
    f_ids, f_items = food
    n_rest = len(r_ids)
    n_users = len(user_ids)
    n_food = len(f_ids)
    if n_food == 0:
        raise SystemExit("error: food dimension has no usable rows")

    base_prices = [config.base_price_for(item) for item in f_items]
    all_food_idx = list(range(n_food))
    # Per-restaurant delivery-time model, so p50/p90 differ by city.
    r_delivery = []
    for city in r_cities:
        city_name = city.rsplit(",", 1)[-1].strip()
        r_delivery.append(config.CITY_DELIVERY.get(city_name, (28, 9)))

    if n_reviews > n_orders:
        sys.stderr.write(
            "[facts] warning: --reviews %d > --orders %d; capping reviews\n"
            % (n_reviews, n_orders)
        )
        n_reviews = n_orders

    # Orders/order_items get their own RNG stream so that changing --reviews
    # never perturbs them.
    rng = random.Random(seed)
    review_rng = random.Random(seed + 1_000_003)
    review_targets = sample_order_offsets(review_rng, n_orders, n_reviews)

    qty_cum = config.cumulative(config.QUANTITY_WEIGHTS)
    pay_cum = config.cumulative(config.PAYMENT_WEIGHTS)
    status_cum = config.cumulative(config.ORDER_STATUS_WEIGHTS)
    fee_cum = config.cumulative(config.DELIVERY_FEE_WEIGHTS)
    rating_cum = config.cumulative(config.CUSTOMER_RATING_WEIGHTS)

    # Line items follow the requested shape: 1 + truncated exponential,
    # capped at 8.  NOTE: the literal 1 + int(expovariate(1/1.3)) does NOT
    # average 2.3 -- int() truncation costs ~0.5, so it averages ~1.86
    # (~18.6M items at 10M orders).  We therefore calibrate lambda so the
    # realised mean matches --order-items-mean: for X ~ Exp(lambda),
    # E[1 + floor(X)] = 1 + 1/(exp(lambda) - 1), hence
    # lambda = ln(mean / (mean - 1)).
    lam = math.log(order_items_mean / (order_items_mean - 1.0))

    start_epoch = (start_date - _EPOCH).days * 86400
    span = (end_date - start_date).days * 86400
    if span <= 0:
        span = 86400
    gap = span // n_orders if n_orders else 0

    orders_path = out_dir / "orders" / "orders.csv"
    items_path = out_dir / "order_items" / "order_items.csv"
    reviews_path = out_dir / "reviews" / "reviews.csv"
    orders_handle, orders_writer = open_output(orders_path, config.HEADER_ORDERS)
    items_handle, items_writer = open_output(items_path, config.HEADER_ORDER_ITEMS)
    reviews_handle, reviews_writer = open_output(reviews_path, config.HEADER_REVIEWS)

    order_item_id = 0
    review_id = 0
    # Expected item count is used only for the progress denominator.
    expected_items = max(1, int(n_orders * order_items_mean))

    try:
        for order_id in range(1, n_orders + 1):
            offset = order_id - 1

            # --- strictly increasing timestamps across the whole range -----
            base_offset = (offset * span) // n_orders if n_orders else 0
            if gap > 1:
                t = start_epoch + base_offset + rng.randrange(gap)
            elif gap == 1:
                t = start_epoch + base_offset
            else:
                # Pathological: more orders than seconds.  Stay deterministic
                # and non-decreasing by stepping one second at a time.
                t = start_epoch + offset
            gm = time.gmtime(t)
            timestamp = "%04d-%02d-%02d %02d:%02d:%02d" % (
                gm.tm_year, gm.tm_mon, gm.tm_mday,
                gm.tm_hour, gm.tm_min, gm.tm_sec,
            )
            order_date = timestamp[:10]

            user_id = user_ids[rng.randrange(n_users)]
            rest_idx = rng.randrange(n_rest)
            r_id = r_ids[rest_idx]
            restaurant_city = r_cities[rest_idx]
            cuisine = r_cuisines[rest_idx]

            choices = all_food_idx
            choice_count = n_food
            if menu is not None:
                bucket = menu.get(r_id)
                if bucket:
                    choices = bucket
                    choice_count = len(bucket)

            # --- line items -------------------------------------------------
            n_items = 1 + int(rng.expovariate(lam))
            if n_items > 8:
                n_items = 8
            subtotal = 0.0
            sales_qty = 0
            for _ in range(n_items):
                food_idx = choices[rng.randrange(choice_count)]
                price = base_prices[food_idx] * (0.95 + 0.10 * rng.random())
                if price < 60.0:
                    price = 60.0
                elif price > 700.0:
                    price = 700.0
                price = round(price, 2)
                quantity = config.QUANTITIES[
                    config.pick_index(qty_cum, rng.random())
                ]
                line_amount = round(price * quantity, 2)
                subtotal += line_amount
                sales_qty += quantity
                order_item_id += 1
                items_writer.writerow([
                    order_item_id, order_id, r_id, f_ids[food_idx],
                    price, quantity, line_amount,
                ])
                _progress("order_items", order_item_id, expected_items)
            subtotal = round(subtotal, 2)

            # --- order-level money -----------------------------------------
            if rng.random() < 0.45:
                discount = 0.0
            else:
                discount = round((0.05 + 0.25 * rng.random()) * subtotal, 2)
            delivery_fee = config.DELIVERY_FEES[
                config.pick_index(fee_cum, rng.random())
            ]
            gst = round(0.05 * (subtotal - discount), 2)
            sales_amount = round(subtotal - discount + delivery_fee + gst, 2)

            payment_method = config.PAYMENT_METHODS[
                config.pick_index(pay_cum, rng.random())
            ]

            # Draw status first, then force Delivered for sampled review
            # orders so the 85/8/7 mix is essentially preserved.
            order_status = config.ORDER_STATUSES[
                config.pick_index(status_cum, rng.random())
            ]
            if offset in review_targets:
                order_status = "Delivered"

            if order_status == "Delivered":
                customer_rating = config.CUSTOMER_RATINGS[
                    config.pick_index(rating_cum, rng.random())
                ]
                base_minutes, spread = r_delivery[rest_idx]
                delivery_time = int(base_minutes + rng.expovariate(1.0 / spread))
                if delivery_time < 15:
                    delivery_time = 15
                elif delivery_time > 90:
                    delivery_time = 90
            else:
                customer_rating = ""
                delivery_time = ""

            orders_writer.writerow([
                order_id, timestamp, order_date, user_id, r_id,
                restaurant_city, cuisine, n_items, sales_qty, subtotal,
                discount, delivery_fee, gst, sales_amount, "INR",
                payment_method, order_status, customer_rating, delivery_time,
            ])
            _progress("orders", order_id, n_orders)

            # --- review (Delivered orders only) -----------------------------
            if offset in review_targets:
                rating = config.review_rating(review_rng)
                comment = config.build_comment(review_rng, rating)
                review_day = t // 86400 + review_rng.randint(0, 14)
                rgm = time.gmtime(review_day * 86400)
                review_date = "%04d-%02d-%02d" % (
                    rgm.tm_year, rgm.tm_mon, rgm.tm_mday
                )
                review_id += 1
                reviews_writer.writerow([
                    review_id, order_id, user_id, r_id, rating, comment,
                    review_date,
                ])
                _progress("reviews", review_id, n_reviews)
    finally:
        orders_handle.close()
        items_handle.close()
        reviews_handle.close()

    return order_item_id, review_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="generate_facts.py",
        description=(
            "Generate the clean Zomato fact CSVs (orders, order_items, "
            "reviews) from dimensions produced by generate_dimensions.py."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="output root; reads and writes <table>/<table>.csv "
             "(default: <project-root>/data/raw)",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument(
        "--small", action="store_true",
        help="fast smoke-test preset (20000 orders, 2000 reviews)",
    )
    parser.add_argument("--orders", type=int, default=None, metavar="N")
    parser.add_argument("--reviews", type=int, default=None, metavar="N")
    parser.add_argument(
        "--order-items-mean", type=float, default=None, metavar="MEAN",
        help="mean line items per order (default 2.3)",
    )
    parser.add_argument("--start-date", default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, metavar="YYYY-MM-DD")
    return parser


def resolve_sizes(args):
    sizes = dict(config.DEFAULTS)
    if args.small:
        sizes.update(config.SMALL_PRESET)
    for key in ("orders", "reviews", "order_items_mean", "start_date", "end_date"):
        value = getattr(args, key)
        if value is not None:
            sizes[key] = value
    if sizes["orders"] < 1:
        raise SystemExit("error: --orders must be >= 1")
    if sizes["reviews"] < 0:
        raise SystemExit("error: --reviews must be >= 0")
    if sizes["order_items_mean"] < 1.0:
        raise SystemExit("error: --order-items-mean must be >= 1.0")
    return sizes


def require_dimension(path, out_dir):
    if not path.exists():
        sys.stderr.write(
            "error: required dimension file not found: %s\n"
            "       generate the dimensions first, for example:\n"
            "         python3 data/generator/generate_dimensions.py "
            "--out-dir %s\n" % (path, out_dir)
        )
        raise SystemExit(2)


def main(argv=None):
    args = build_parser().parse_args(argv)
    sizes = resolve_sizes(args)
    out_dir = config.resolve_out_dir(args.out_dir)

    restaurants_path = out_dir / "restaurants" / "restaurants.csv"
    users_path = out_dir / "users" / "users.csv"
    food_path = out_dir / "food" / "food.csv"
    menu_path = out_dir / "menu" / "menu.csv"
    require_dimension(restaurants_path, out_dir)
    require_dimension(users_path, out_dir)
    require_dimension(food_path, out_dir)

    start_date = date.fromisoformat(sizes["start_date"])
    end_date = date.fromisoformat(sizes["end_date"])
    if end_date < start_date:
        raise SystemExit("error: --end-date must be on or after --start-date")

    sys.stderr.write(
        "[facts] seed=%d out-dir=%s orders=%d reviews=%d mean=%.2f "
        "range=%s..%s\n" % (
            args.seed, out_dir, sizes["orders"], sizes["reviews"],
            sizes["order_items_mean"], start_date, end_date,
        )
    )
    sys.stderr.flush()

    restaurants = load_restaurants(restaurants_path)
    users = load_users(users_path)
    f_ids, f_items = load_food(food_path)
    if not restaurants[0]:
        raise SystemExit("error: no usable rows in %s" % restaurants_path)
    if not users:
        raise SystemExit("error: no usable rows in %s" % users_path)
    food_index = {f_id: i for i, f_id in enumerate(f_ids)}
    menu = load_menu(menu_path, food_index)
    if menu is None:
        sys.stderr.write(
            "[facts] note: menu.csv not found; order items are drawn from the "
            "full food dimension\n"
        )
    else:
        sys.stderr.write(
            "[facts] loaded %d restaurants, %d users, %d food items, "
            "%d menu buckets\n" % (len(restaurants[0]), len(users),
                                   len(f_ids), len(menu))
        )
    sys.stderr.flush()

    n_items, n_reviews = write_facts(
        out_dir, restaurants, users, (f_ids, f_items), menu,
        sizes["orders"], sizes["reviews"], sizes["order_items_mean"],
        start_date, end_date, args.seed,
    )
    sys.stderr.write(
        "[facts] done: order_items=%d reviews=%d\n" % (n_items, n_reviews)
    )
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
