"""Reusable behavioral sanity cases; never used as training or output rules."""
NORMAL_CONTROL = {"amount": 500, "transaction_type": "online_purchase", "transaction_hour": 14,
    "merchant_category": "groceries", "device_type": "mobile", "is_new_device": 0,
    "location_type": "usual", "account_age_days": 1000, "transactions_last_24h": 2,
    "average_transaction_amount": 600}
SUSPICIOUS_CONTROL = {"amount": 80000, "transaction_type": "bank_transfer", "transaction_hour": 2,
    "merchant_category": "retail", "device_type": "desktop", "is_new_device": 1,
    "location_type": "unusual_domestic", "account_age_days": 30, "transactions_last_24h": 15,
    "average_transaction_amount": 1500}
MIXED_CASES = {
    "large_but_established": {"amount": 12000, "transaction_type": "card_payment", "transaction_hour": 16,
        "merchant_category": "travel", "device_type": "mobile", "is_new_device": 0,
        "location_type": "usual", "account_age_days": 2500, "transactions_last_24h": 3,
        "average_transaction_amount": 3000},
    "small_but_unusual": {"amount": 700, "transaction_type": "online_purchase", "transaction_hour": 3,
        "merchant_category": "gaming", "device_type": "desktop", "is_new_device": 1,
        "location_type": "international", "account_age_days": 500, "transactions_last_24h": 5,
        "average_transaction_amount": 650},
    "bursty_transfer": {"amount": 2500, "transaction_type": "bank_transfer", "transaction_hour": 11,
        "merchant_category": "utilities", "device_type": "mobile", "is_new_device": 0,
        "location_type": "usual", "account_age_days": 800, "transactions_last_24h": 14,
        "average_transaction_amount": 1800},
}
