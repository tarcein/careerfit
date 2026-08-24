def calculate_ranking_metrics(cases: list[dict]) -> dict:
    if not cases:
        return {"case_count": 0, "top1_accuracy": 0.0, "precision_at_3": 0.0, "recall_at_3": 0.0, "mrr": 0.0}
    top1 = precision = recall = reciprocal_rank = 0.0
    for case in cases:
        predicted = case["predicted"][:3]
        truth = case["truth"][:3]
        overlap = len(set(predicted) & set(truth))
        top1 += bool(predicted and truth and predicted[0] == truth[0])
        precision += overlap / 3
        recall += overlap / len(truth) if truth else 0
        if truth and truth[0] in predicted:
            reciprocal_rank += 1 / (predicted.index(truth[0]) + 1)
    count = len(cases)
    return {
        "case_count": count,
        "top1_accuracy": round(top1 / count * 100, 1),
        "precision_at_3": round(precision / count * 100, 1),
        "recall_at_3": round(recall / count * 100, 1),
        "mrr": round(reciprocal_rank / count, 3),
    }
