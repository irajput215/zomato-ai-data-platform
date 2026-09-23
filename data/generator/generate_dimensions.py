#!/usr/bin/env python3
"""Generate the four deliberately MESSY Zomato dimension CSVs.

Produces, under ``<out-dir>/<table>/<table>.csv``:

    restaurants, users, food, menu

The output is byte-for-byte reproducible for a given ``--seed``.  Rows are
streamed straight to a buffered ``csv.writer`` (never accumulated in memory).

Run directly (no package install required)::

    python3 data/generator/generate_dimensions.py --small
    python3 data/generator/generate_dimensions.py --restaurants 148541 --users 200000
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
import re
import sys
from pathlib import Path

try:  # normal package import (python -m data.generator.generate_dimensions)
    from . import config
except ImportError:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config

_SLUG_RE = re.compile(r"[^a-z0-9]+")

BUILDING_NAMES = (
    "Ground Floor", "1st Floor", "2nd Floor", "Shop No 4", "Shop No 12",
    "Door No 21", "Plot 7", "Building A", "Tower B", "Unit 3",
    "Near Metro Station", "Opposite Bus Stand", "Next to City Mall",
)


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


def _slug(text):
    return _SLUG_RE.sub("-", text.lower()).strip("-")


# ---------------------------------------------------------------------------
# food.csv
# ---------------------------------------------------------------------------
def write_food(out_dir, n_food, rng):
    """Return (food_ids, food_name_by_id) while writing food.csv."""
    path = out_dir / "food" / "food.csv"
    food_ids = []
    name_by_id = {}
    # ~0.5% of rows drop their LAST field: (idx, f_id, item) with no
    # veg_or_non_veg.  Snowflake NULL-fills the rest thanks to
    # ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE and stg_food maps that null to a
    # null flag.
    #
    # ONLY the trailing column is dropped, deliberately: `item` must survive,
    # because stg_food tests food_name as not_null and dim_food would otherwise
    # carry nameless dishes.  A seeded stride (rather than an independent 0.5%
    # coin flip) guarantees the path is exercised even for tiny --small runs.
    short_stride = 200
    short_offset = rng.randrange(short_stride)
    handle, writer = open_output(path, config.HEADER_FOOD)
    try:
        for i in range(1, n_food + 1):
            idx = i - 1
            if rng.random() < 0.62:
                item = rng.choice(config.VEG_DISHES)
                label = rng.choice(config.VEG_LABELS)
            else:
                item = rng.choice(config.NON_VEG_DISHES)
                label = rng.choice(config.NON_VEG_LABELS)
            modifier = rng.choice(config.FOOD_MODIFIERS)
            if modifier:
                item = "%s %s" % (item, modifier)
            f_id = str(i)
            food_ids.append(f_id)
            name_by_id[f_id] = item
            if (i - short_offset) % short_stride == 0:
                writer.writerow([idx, f_id, item])
            else:
                writer.writerow([idx, f_id, item, label])
            _progress("food", i, n_food)
    finally:
        handle.close()
    return food_ids, name_by_id


# ---------------------------------------------------------------------------
# restaurants.csv + menu.csv (single pass, two open writers)
# ---------------------------------------------------------------------------
def write_restaurants_and_menu(out_dir, n_restaurants, menu_per_restaurant,
                               food_ids, name_by_id, rng):
    rest_path = out_dir / "restaurants" / "restaurants.csv"
    menu_path = out_dir / "menu" / "menu.csv"
    rest_handle, rest_writer = open_output(rest_path, config.HEADER_RESTAURANTS)
    menu_handle, menu_writer = open_output(menu_path, config.HEADER_MENU)

    city_cum = config.cumulative(config.CITY_WEIGHTS)
    cuisine_cum = config.cumulative(config.CUISINE_WEIGHTS)
    n_food = len(food_ids)
    menu_id = 0
    total_menu = n_restaurants * menu_per_restaurant

    try:
        for i in range(1, n_restaurants + 1):
            idx = i - 1
            city = config.CITIES[config.pick_index(city_cum, rng.random())]
            area = rng.choice(config.CITY_AREAS[city])
            city_full = "%s, %s" % (area, city)
            cuisine = config.CUISINES[config.pick_index(cuisine_cum, rng.random())]

            name = "%s %s %s" % (
                rng.choice(config.RESTAURANT_PREFIXES),
                cuisine,
                rng.choice(config.RESTAURANT_SUFFIXES),
            )

            # rating: ~86% decimal string, ~12% literal '--', a few 'NEW'
            r = rng.random()
            if r < 0.12:
                rating = "--"
            elif r < 0.14:
                rating = "NEW"
            else:
                rating = "%.1f" % (2.5 + rng.random() * 2.5)

            # rating_count: digits only (no thousands separators)
            count = 3 + int((rng.random() ** 3) * 20_000)
            if count < 1000:
                rating_count = "%d+ ratings" % count
            else:
                rating_count = "%d ratings" % count

            # cost: '₹ <int>' optionally followed by ' for two' (no separators)
            cost_value = rng.randint(100, 3000)
            cost_value = max(100, min(3000, int(round(cost_value / 50.0)) * 50))
            cost = "\u20b9 %d%s" % (
                cost_value, " for two" if rng.random() < 0.6 else ""
            )

            lic_no = str(rng.randint(10 ** 11, 10 ** 12 - 1))
            link = "https://www.zomato.com/%s/%s-%s" % (
                _slug(city), _slug(name), _slug(area)
            )
            address = "%s, %s, %s - %d" % (
                rng.choice(BUILDING_NAMES), area, city, rng.randint(110001, 799999)
            )

            # Pick this restaurant's menu items first so the `menu` text column
            # reflects the same dishes written to menu.csv.
            picked = []
            for _ in range(menu_per_restaurant):
                f_id = food_ids[rng.randrange(n_food)]
                base = config.base_price_for(name_by_id[f_id])
                price = round(base * (1.0 + 0.40 * rng.random()), 2)
                if price <= 0:
                    price = 60.0
                menu_id += 1
                menu_writer.writerow(
                    [menu_id - 1, str(menu_id), str(i), f_id, cuisine,
                     config.format_price(price)]
                )
                picked.append(name_by_id[f_id])
                _progress("menu", menu_id, total_menu)

            menu_text = ", ".join(picked)

            rest_writer.writerow([
                idx, str(i), name, city_full, rating, rating_count, cost,
                cuisine, lic_no, link, address, menu_text,
            ])
            _progress("restaurants", i, n_restaurants)
    finally:
        rest_handle.close()
        menu_handle.close()


# ---------------------------------------------------------------------------
# users.csv
# ---------------------------------------------------------------------------
def _mixed_case(rng, word):
    style = rng.randrange(3)
    if style == 0:
        return word.lower()
    if style == 1:
        return word.capitalize()
    return word.upper()


def write_users(out_dir, n_users, seed, rng):
    path = out_dir / "users" / "users.csv"
    handle, writer = open_output(path, config.HEADER_USERS)
    gender_cum = config.cumulative(config.GENDER_WEIGHTS)
    marital_cum = config.cumulative(config.MARITAL_WEIGHTS)
    occupation_cum = config.cumulative(config.OCCUPATION_WEIGHTS)
    education_cum = config.cumulative(config.EDUCATION_WEIGHTS)
    income_cum = config.cumulative(config.INCOME_WEIGHTS)
    try:
        for i in range(1, n_users + 1):
            idx = i - 1
            first = rng.choice(config.FIRST_NAMES)
            last = rng.choice(config.LAST_NAMES)
            name = "%s %s" % (first, last)
            email = "%s.%s@%s" % (
                _mixed_case(rng, first), _mixed_case(rng, last),
                rng.choice(config.EMAIL_DOMAINS),
            )
            password = hashlib.sha256(
                ("%s:%d" % (seed, i)).encode("utf-8")
            ).hexdigest()[:24]

            age = "NA" if rng.random() < 0.03 else str(rng.randint(18, 65))
            gender = config.GENDERS[config.pick_index(gender_cum, rng.random())]
            marital = config.MARITAL_STATUSES[
                config.pick_index(marital_cum, rng.random())
            ]
            occupation = config.OCCUPATIONS[
                config.pick_index(occupation_cum, rng.random())
            ]
            income = config.INCOME_BANDS[
                config.pick_index(income_cum, rng.random())
            ]
            education = config.EDUCATION_LEVELS[
                config.pick_index(education_cum, rng.random())
            ]
            family_size = str(rng.randint(1, 6))

            writer.writerow([
                idx, str(i), name, email, password, age, gender, marital,
                occupation, income, education, family_size,
            ])
            _progress("users", i, n_users)
    finally:
        handle.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="generate_dimensions.py",
        description=(
            "Generate messy Zomato dimension CSVs (restaurants, users, food, "
            "menu) exactly matching the Snowflake RAW COPY INTO contract."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="output root; one <table>/<table>.csv per table "
             "(default: <project-root>/data/raw)",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument(
        "--small", action="store_true",
        help="fast smoke-test preset (500 restaurants, 2000 users, 300 food, "
             "3 menu per restaurant)",
    )
    parser.add_argument("--restaurants", type=int, default=None, metavar="N")
    parser.add_argument("--users", type=int, default=None, metavar="N")
    parser.add_argument("--food", type=int, default=None, metavar="N")
    parser.add_argument(
        "--menu-per-restaurant", type=int, default=None, metavar="N"
    )
    return parser


def resolve_sizes(args):
    sizes = dict(config.DEFAULTS)
    if args.small:
        sizes.update(config.SMALL_PRESET)
    for key in ("restaurants", "users", "food", "menu_per_restaurant"):
        value = getattr(args, key)
        if value is not None:
            sizes[key] = value
    for key in ("restaurants", "users", "food", "menu_per_restaurant"):
        if sizes[key] < 1:
            raise SystemExit("error: --%s must be >= 1" % key.replace("_", "-"))
    return sizes


def main(argv=None):
    args = build_parser().parse_args(argv)
    sizes = resolve_sizes(args)
    out_dir = config.resolve_out_dir(args.out_dir)
    rng = random.Random(args.seed)

    sys.stderr.write(
        "[dimensions] seed=%d out-dir=%s restaurants=%d users=%d food=%d "
        "menu/restaurant=%d\n" % (
            args.seed, out_dir, sizes["restaurants"], sizes["users"],
            sizes["food"], sizes["menu_per_restaurant"],
        )
    )
    sys.stderr.flush()

    food_ids, name_by_id = write_food(out_dir, sizes["food"], rng)
    write_restaurants_and_menu(
        out_dir, sizes["restaurants"], sizes["menu_per_restaurant"],
        food_ids, name_by_id, rng,
    )
    write_users(out_dir, sizes["users"], args.seed, rng)

    sys.stderr.write("[dimensions] done\n")
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
