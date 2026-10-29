"""Generate a reproducible educational synthetic transaction dataset."""
import csv
import math
import random
from pathlib import Path

RANDOM_SEED = 42
NUMBER_OF_ROWS = 20_000
OUTPUT_FILE = Path(__file__).parent / "dataset" / "transactions.csv"

def weighted_choice(rng, choices):
    values, weights = zip(*choices)
    return rng.choices(values, weights=weights, k=1)[0]

def fraud_probability(transaction):
    """Sample from overlapping behavioural risk; no field determines the label."""
    ratio = transaction["amount"] / max(transaction["average_transaction_amount"], 1)
    unusual_hour = transaction["transaction_hour"] <= 4
    unusual_location = transaction["location_type"] != "usual"
    risky_context = transaction["transaction_type"] in {"bank_transfer", "crypto_purchase"}
    score = -4.55
    score += 0.70 * min(max(math.log(max(ratio, 0.1)), 0), 3.5)
    score += 0.80 * unusual_hour + 0.90 * transaction["is_new_device"]
    score += 0.55 * (transaction["location_type"] == "unusual_domestic")
    score += 1.10 * (transaction["location_type"] == "international")
    score += 0.70 * risky_context
    score += 0.070 * min(transaction["transactions_last_24h"], 25)
    score += 0.75 * (transaction["account_age_days"] < 90)
    score += 0.30 * (transaction["merchant_category"] in {"electronics", "gaming"})
    score += 1.05 * (transaction["is_new_device"] and unusual_location)
    score += 0.95 * (ratio > 4 and unusual_hour)
    score += 0.75 * (risky_context and transaction["transactions_last_24h"] >= 10)
    return 1 / (1 + math.exp(-score))

def create_transaction(rng, row_number):
    average_amount = round(min(rng.lognormvariate(6.2, 0.85), 20_000), 2)
    multiplier = rng.lognormvariate(0, 0.70)
    if rng.random() < 0.025:  # occasional genuine-looking spending spikes
        multiplier *= rng.uniform(4, 12)
    transaction = {
        "transaction_id": f"TXN{row_number:06d}",
        "amount": round(min(max(1, average_amount * multiplier), 150_000), 2),
        "transaction_type": weighted_choice(rng, [("card_payment", 48), ("online_purchase", 25), ("bank_transfer", 17), ("cash_withdrawal", 7), ("crypto_purchase", 3)]),
        "transaction_hour": weighted_choice(rng, [(hour, 1 if hour <= 5 else 5 if 9 <= hour <= 21 else 3) for hour in range(24)]),
        "device_type": weighted_choice(rng, [("mobile", 62), ("desktop", 27), ("tablet", 7), ("atm", 4)]),
        "is_new_device": int(rng.random() < 0.14),
        "location_type": weighted_choice(rng, [("usual", 74), ("unusual_domestic", 18), ("international", 8)]),
        "merchant_category": weighted_choice(rng, [("groceries", 21), ("retail", 20), ("restaurants", 16), ("utilities", 12), ("travel", 9), ("electronics", 9), ("entertainment", 8), ("gaming", 5)]),
        "account_age_days": rng.randint(15, 3_650),
        "transactions_last_24h": min(int(rng.expovariate(1 / 5.0)), 35),
        "average_transaction_amount": average_amount,
    }
    transaction["is_fraud"] = int(rng.random() < fraud_probability(transaction))
    return transaction

def generate_dataset():
    rng = random.Random(RANDOM_SEED)
    rows = [create_transaction(rng, number) for number in range(1, NUMBER_OF_ROWS + 1)]
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(rows)
    fraud_count = sum(row["is_fraud"] for row in rows)
    print(f"Generated {len(rows):,} transactions at {OUTPUT_FILE}")
    print(f"Genuine: {len(rows) - fraud_count:,}")
    print(f"Fraud: {fraud_count:,} ({fraud_count / len(rows):.2%})")

if __name__ == "__main__":
    generate_dataset()
