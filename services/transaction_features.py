def raw_transaction_from_model(transaction):
    return {
        "amount": float(transaction.amount),
        "transaction_type": transaction.transaction_type,
        "transaction_hour": transaction.transaction_hour,
        "device_type": transaction.device_type,
        "is_new_device": int(transaction.is_new_device),
        "location_type": transaction.location_type,
        "merchant_category": transaction.merchant_category,
        "account_age_days": transaction.account_age_days,
        "transactions_last_24h": transaction.transactions_last_24h,
        "average_transaction_amount": float(transaction.average_transaction_amount),
    }
