"""
Generate test M5 data for development and testing.
Creates small CSV files with the same structure as the real M5 dataset.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_sales_wide(num_items=100, num_stores=5, num_days=365):
    """Generate mock sales data in wide format."""
    data = []
    date_range = pd.date_range(start='2011-01-29', periods=num_days)

    for item_id in range(num_items):
        for store_id in range(num_stores):
            category = ['FOODS', 'HOBBIES', 'HOUSEHOLD'][item_id % 3]
            item_name = f"ITEM_{item_id:05d}"

            row = {'id': f"{item_name}_{store_id:02d}"}

            # Generate sales for each day
            base_sales = np.random.poisson(lam=15)
            for day_num in range(1, num_days + 1):
                # Add some trend and seasonality
                trend = day_num * 0.01
                seasonality = 10 * np.sin(2 * np.pi * day_num / 7)
                noise = np.random.normal(0, 5)
                sales = max(0, int(base_sales + trend + seasonality + noise))
                row[f'd_{day_num}'] = sales

            data.append(row)

    df = pd.DataFrame(data)
    return df


def generate_sell_prices(num_items=100, num_stores=5, num_days=365):
    """Generate mock sell prices data."""
    data = []

    for item_id in range(num_items):
        for store_id in range(num_stores):
            item_name = f"ITEM_{item_id:05d}"

            for day_num in range(1, num_days + 1):
                # Random prices between 1 and 50
                price = round(np.random.uniform(1.0, 50.0), 2)

                data.append({
                    'store_id': store_id,
                    'item_id': item_name,
                    'wm_yr_wk': 1 + (day_num - 1) // 7,  # Week number
                    'sell_price': price
                })

    df = pd.DataFrame(data)
    return df.drop_duplicates(subset=['store_id', 'item_id', 'wm_yr_wk'])


def generate_calendar(num_days=365):
    """Generate mock calendar data."""
    date_range = pd.date_range(start='2011-01-29', periods=num_days)

    events = [
        'SuperBowl', 'Valentine', 'StPatrick', 'Easter', 'Mothers',
        'Fathers', 'Independence', 'Labor', 'Halloween', 'Christmas'
    ]

    data = []
    for idx, date in enumerate(date_range):
        day_num = idx + 1
        week_num = 1 + (day_num - 1) // 7

        event_name = None
        event_type = None

        # Randomly assign events
        if np.random.random() < 0.05:
            event_name = np.random.choice(events)
            event_type = np.random.choice(['Cultural', 'Sporting', 'National', 'Religious'])

        data.append({
            'd': day_num,
            'date': date.strftime('%Y-%m-%d'),
            'wm_yr_wk': week_num,
            'weekday': date.strftime('%A'),
            'month': date.month,
            'year': date.year,
            'event_name_1': event_name,
            'event_type_1': event_type,
            'snap_CA': 1 if np.random.random() < 0.3 else 0,
            'snap_TX': 1 if np.random.random() < 0.3 else 0,
            'snap_WI': 1 if np.random.random() < 0.3 else 0,
        })

    df = pd.DataFrame(data)
    return df


def main():
    import os

    # Create output directory if it doesn't exist
    output_dir = 'data/raw'
    os.makedirs(output_dir, exist_ok=True)

    print("Generating test M5 data...")

    # Generate and save sales data
    print("  Generating sales_train_validation.csv...")
    sales_df = generate_sales_wide(num_items=100, num_stores=5, num_days=365)
    sales_df.to_csv(f'{output_dir}/sales_train_validation.csv', index=False)
    print(f"    ✓ {sales_df.shape[0]} rows × {sales_df.shape[1]} columns")

    # Generate and save prices data
    print("  Generating sell_prices.csv...")
    prices_df = generate_sell_prices(num_items=100, num_stores=5, num_days=365)
    prices_df.to_csv(f'{output_dir}/sell_prices.csv', index=False)
    print(f"    ✓ {prices_df.shape[0]} rows")

    # Generate and save calendar data
    print("  Generating calendar.csv...")
    calendar_df = generate_calendar(num_days=365)
    calendar_df.to_csv(f'{output_dir}/calendar.csv', index=False)
    print(f"    ✓ {calendar_df.shape[0]} rows")

    print("Test data generated successfully!")


if __name__ == '__main__':
    main()
