import math
from collections import defaultdict
from datetime import datetime, timedelta

from services.behavioral_anomaly import behavioral_risk_level


MAX_GRAPH_RELATIONSHIPS = 75


def _timestamp(row):
    try:
        return datetime.fromisoformat(str(row.get("transaction_date", "")))
    except (TypeError, ValueError):
        return None


def _round(value, digits=2):
    return round(float(value or 0), digits)


def _node_size(transaction_count):
    """Frequency-based node diameter, bounded to 34-72 CSS pixels."""
    return round(min(72, 34 + 12 * math.log2(max(1, transaction_count))), 1)


def _edge_width(transaction_count, total_amount, maximum_total):
    """Balanced frequency/amount thickness, bounded to 2-10 CSS pixels."""
    frequency = math.log1p(transaction_count) / math.log(2)
    amount = math.log1p(max(0, total_amount)) / math.log1p(max(1, maximum_total))
    return round(min(10, 2 + 2 * frequency + 4 * amount), 1)


def _relationship_score(rows, spending_concentration):
    scores = [float(row.get("behavioral_score", 0) or 0) for row in rows]
    high_count = sum(row.get("final_risk_level") == "HIGH" for row in rows)
    base = 0.55 * (sum(scores) / len(scores)) + 0.25 * max(scores)
    base += 20 * (high_count / len(rows))
    # Concentration is supporting evidence, deliberately capped so amount alone
    # can never turn an otherwise normal relationship HIGH risk.
    if max(scores) >= 30:
        base += min(8, spending_concentration * 12)
    return round(max(0, min(100, base)), 1)


def _signals(rows, transaction_count, spending_concentration, merchant_count):
    reasons = " ".join(
        reason.casefold()
        for row in rows
        for reason in (row.get("risk_reasons") or [])
    )
    timestamps = sorted(timestamp for row in rows if (timestamp := _timestamp(row)))
    amounts = [float(row.get("amount", 0) or 0) for row in rows]
    signals = []
    if any("amount" in reason.casefold() for row in rows for reason in row.get("risk_reasons", [])):
        signals.append("High Value")
    if transaction_count >= 2 and (
        "repeated payment" in reasons
        or (max(amounts, default=0) - min(amounts, default=0) <= max(1, max(amounts, default=0) * 0.02))
    ):
        signals.append("Repeated Payments")
    if transaction_count <= 1 and merchant_count >= 3:
        signals.append("Rare Payee")
    if any(timestamp.hour < 5 for timestamp in timestamps):
        signals.append("Late-Hour Activity")
    if any(later - earlier <= timedelta(hours=1) for earlier, later in zip(timestamps, timestamps[1:])):
        signals.append("Transaction Burst")
    if spending_concentration >= 0.35:
        signals.append("Spending Concentration")
    return signals


def _clusters(relationships, all_rows):
    clusters = []
    repeated_high = [item for item in relationships if item["high_risk_count"] >= 2]
    if repeated_high:
        clusters.append({"name": "Repeated High-Risk Merchant Cluster", "count": len(repeated_high), "evidence": "Payees with two or more HIGH-risk transactions."})
    burst = [item for item in relationships if "Transaction Burst" in item["risk_indicators"]]
    if burst:
        clusters.append({"name": "Rapid Payment Burst", "count": len(burst), "evidence": "Payees with transactions no more than one hour apart."})
    concentrated = [item for item in relationships if "Spending Concentration" in item["risk_indicators"]]
    if concentrated:
        clusters.append({"name": "High-Value Concentration", "count": len(concentrated), "evidence": "Payees receiving at least 35% of statement spending."})
    rare_risky = [item for item in relationships if "Rare Payee" in item["risk_indicators"] and item["relationship_risk_score"] >= 30]
    if len(rare_risky) >= 2:
        clusters.append({"name": "Multiple Rare Payees", "count": len(rare_risky), "evidence": "Multiple one-time payees with elevated relationship risk."})
    late = [item for item in relationships if "Late-Hour Activity" in item["risk_indicators"] and item["relationship_risk_score"] >= 30]
    if late:
        clusters.append({"name": "Late-Night Payment Cluster", "count": len(late), "evidence": "Elevated-risk payees with activity between midnight and 05:00."})
    return clusters


def _insights(relationships, total_spending, total_high):
    if not relationships:
        return []
    frequent = sum(item["transaction_count"] >= 2 for item in relationships)
    suspicious = sum(item["relationship_risk_score"] >= 30 for item in relationships)
    messages = []
    if frequent:
        messages.append(f"Activity includes {frequent} frequently used payee{'s' if frequent != 1 else ''} with two or more transactions.")
    if suspicious:
        messages.append(f"{suspicious} relationship{'s contain' if suspicious != 1 else ' contains'} elevated behavioral risk.")
    leader = max(relationships, key=lambda item: item["spending_concentration_pct"])
    if leader["spending_concentration_pct"] >= 20:
        detail = f"{leader['merchant_or_payee']} accounts for {leader['spending_concentration_pct']:.1f}% of statement spending"
        if leader["high_risk_count"]:
            detail += f" and includes {leader['high_risk_count']} HIGH-risk transaction{'s' if leader['high_risk_count'] != 1 else ''}"
        messages.append(detail + ".")
    if total_high:
        risk_leader = max(relationships, key=lambda item: item["risk_concentration_pct"])
        if risk_leader["risk_concentration_pct"] >= 25:
            messages.append(f"{risk_leader['merchant_or_payee']} contains {risk_leader['risk_concentration_pct']:.1f}% of all HIGH-risk statement activity.")
    return messages


def build_transaction_network(analysis, max_relationships=MAX_GRAPH_RELATIONSHIPS):
    rows = [row for row in analysis.get("results", []) if str(row.get("merchant_or_payee") or "").strip()]
    if not rows:
        return {
            "available": False,
            "message": "A relationship network cannot be created because this statement does not contain merchant/payee information.",
            "nodes": [], "edges": [], "relationships": [], "clusters": [], "insights": [],
            "summary": {"unique_payees": 0, "total_relationships": 0, "suspicious_relationships": 0, "high_risk_payees": 0, "largest_relationship": None, "most_frequent_payee": None},
            "display_limit": max_relationships,
        }

    grouped = defaultdict(list)
    for row in rows:
        # Exact normalized labels aggregate repeats; fuzzy matching is intentionally absent.
        grouped[str(row["merchant_or_payee"]).strip()].append(row)
    total_spending = sum(float(row.get("amount", 0) or 0) for row in rows)
    total_high = sum(row.get("final_risk_level") == "HIGH" for row in rows)
    relationships = []
    for index, (merchant, merchant_rows) in enumerate(grouped.items(), start=1):
        ordered = sorted(merchant_rows, key=lambda row: _timestamp(row) or datetime.min)
        amounts = [float(row.get("amount", 0) or 0) for row in ordered]
        scores = [float(row.get("behavioral_score", 0) or 0) for row in ordered]
        total = sum(amounts)
        spending_share = total / total_spending if total_spending else 0
        high_count = sum(row.get("final_risk_level") == "HIGH" for row in ordered)
        score = _relationship_score(ordered, spending_share)
        first_ts = _timestamp(ordered[0])
        last_ts = _timestamp(ordered[-1])
        item = {
            "id": f"payee-{index}", "merchant_or_payee": merchant,
            "transaction_count": len(ordered), "total_amount": _round(total),
            "average_amount": _round(total / len(ordered)), "maximum_amount": _round(max(amounts)),
            "average_risk": _round(sum(scores) / len(scores), 1), "maximum_risk": _round(max(scores), 1),
            "high_risk_count": high_count,
            "first_observed": first_ts.isoformat(timespec="minutes") if first_ts else str(ordered[0].get("transaction_date", "")),
            "last_observed": last_ts.isoformat(timespec="minutes") if last_ts else str(ordered[-1].get("transaction_date", "")),
            "is_rare": len(ordered) <= 1 and len(grouped) >= 3,
            "spending_concentration_pct": _round(spending_share * 100, 1),
            "risk_concentration_pct": _round((high_count / total_high * 100) if total_high else 0, 1),
            "relationship_risk_score": score, "risk_level": behavioral_risk_level(score),
            "transactions": [{
                "row_number": row.get("statement_row_number"), "date": row.get("transaction_date", ""),
                "amount": _round(row.get("amount")), "risk_score": _round(row.get("behavioral_score"), 1),
                "risk_level": row.get("final_risk_level", "LOW"),
                "reason": "; ".join((row.get("risk_reasons") or [])[:2]) or "No significant indicators",
                "investigable": row.get("final_risk_level") in {"MEDIUM", "HIGH"},
            } for row in ordered],
        }
        item["risk_indicators"] = _signals(ordered, len(ordered), spending_share, len(grouped))
        relationships.append(item)

    relationships.sort(key=lambda item: (item["relationship_risk_score"], item["high_risk_count"], item["total_amount"]), reverse=True)
    # Risk always wins display priority, followed by relationship score and activity.
    visible = sorted(relationships, key=lambda item: (item["high_risk_count"] > 0, item["relationship_risk_score"], item["transaction_count"], item["total_amount"]), reverse=True)[:max_relationships]
    visible_ids = {item["id"] for item in visible}
    maximum_total = max(item["total_amount"] for item in visible)
    nodes = [{"data": {"id": "account", "label": "My Account", "type": "ACCOUNT", "risk_level": "LOW", "size": 58}}]
    edges = []
    for item in relationships:
        item["displayed"] = item["id"] in visible_ids
        if not item["displayed"]:
            continue
        nodes.append({"data": {"id": item["id"], "label": item["merchant_or_payee"], "type": "PAYEE", "risk_level": item["risk_level"], "size": _node_size(item["transaction_count"]), "relationship_id": item["id"]}})
        edges.append({"data": {"id": f"edge-{item['id']}", "source": "account", "target": item["id"], "label": f"{item['transaction_count']} txn", "risk_level": item["risk_level"], "width": _edge_width(item["transaction_count"], item["total_amount"], maximum_total), "relationship_id": item["id"]}})

    largest = max(relationships, key=lambda item: item["total_amount"])
    frequent = max(relationships, key=lambda item: item["transaction_count"])
    return {
        "available": True, "nodes": nodes, "edges": edges, "relationships": relationships,
        "clusters": _clusters(relationships, rows), "insights": _insights(relationships, total_spending, total_high),
        "summary": {
            "unique_payees": len(relationships), "total_relationships": len(relationships),
            "suspicious_relationships": sum(item["relationship_risk_score"] >= 30 for item in relationships),
            "high_risk_payees": sum(item["risk_level"] == "HIGH" for item in relationships),
            "largest_relationship": {"name": largest["merchant_or_payee"], "amount": largest["total_amount"]},
            "most_frequent_payee": {"name": frequent["merchant_or_payee"], "count": frequent["transaction_count"]},
        },
        "display_limit": max_relationships, "displayed_relationships": len(visible),
    }
