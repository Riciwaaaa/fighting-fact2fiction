# evaluate_veracity_baseline.py
#
# MODIFIED from the official AVeriTeC evaluate_veracity.py.
#
# WHY modified:
#   This baseline produces no evidence/questions — only a pred_label.
#   The original script's question-only, Q&A, and AVeriTeC score metrics all
#   require predicted evidence and crash or return 0 without it.
#   We keep only evaluate_veracity() which is pure label comparison.
#
# WHAT changed vs. original:
#   - __main__ only calls evaluate_veracity(); other metric calls removed.
#   - evaluate_veracity() normalises the data's "Cherry-picking" spelling to
#     the evaluator's "Cherrypicking" so sklearn label IDs match correctly.
#   - Default paths updated to match our project layout.
#
# Prediction format (from result_store.write_eval_json):
#   [{"pred_label": "Supported"}, ...]

import argparse
import json
import numpy as np
import sklearn.metrics
import nltk
from nltk import word_tokenize


def pairwise_meteor(candidate, reference):
    return nltk.translate.meteor_score.single_meteor_score(
        word_tokenize(reference), word_tokenize(candidate)
    )


def compute_all_pairwise_scores(src_data, tgt_data, metric):
    scores = np.empty((len(src_data), len(tgt_data)))
    for i, src in enumerate(src_data):
        for j, tgt in enumerate(tgt_data):
            scores[i][j] = metric(src, tgt)
    return scores


def print_with_space(left, right, left_space=45):
    print(" " * (left_space - len(left)), end="")
    print(left + " " * (left_space - len(left)) + right)


class AVeriTeCEvaluator:

    verdicts = [
        "Supported",
        "Refuted",
        "Not Enough Evidence",
        "Conflicting Evidence/Cherrypicking",  # no hyphen — sklearn label ID
    ]
    pairwise_metric = None
    max_questions = 10
    metric = None
    averitec_reporting_levels = [0.1, 0.2, 0.25, 0.3, 0.4, 0.5]

    def __init__(self, metric="meteor"):
        self.metric = metric
        if metric == "meteor":
            self.pairwise_metric = pairwise_meteor

    def evaluate_veracity(self, src, tgt):
        """
        Accuracy + per-class F1 + macro-F1 from predicted labels only.
        No evidence fields required.
        """
        src_labels = [x["pred_label"] for x in src]
        tgt_labels = [x["label"] for x in tgt]

        # Normalise data spelling → evaluator spelling so label IDs match.
        # WHY: dev.json uses "Cherry-picking" (hyphen); verdicts list uses
        # "Cherrypicking" (no hyphen). Mismatch causes that class to score 0.
        tgt_labels = [
            "Conflicting Evidence/Cherrypicking"
            if l == "Conflicting Evidence/Cherry-picking" else l
            for l in tgt_labels
        ]

        acc = float(np.mean([s == t for s, t in zip(src_labels, tgt_labels)]))

        f1 = {
            self.verdicts[i]: x
            for i, x in enumerate(
                sklearn.metrics.f1_score(
                    tgt_labels, src_labels,
                    labels=self.verdicts, average=None, zero_division=0,
                )
            )
        }
        f1["macro"] = float(sklearn.metrics.f1_score(
            tgt_labels, src_labels,
            labels=self.verdicts, average="macro", zero_division=0,
        ))
        f1["acc"] = acc
        return f1

    # ── Remaining methods kept from original (unused here) ────────────────────

    def evaluate_averitec_veracity_by_type(self, srcs, tgts, threshold=0.25):
        types = {}
        for src, tgt in zip(srcs, tgts):
            score = self.compute_pairwise_evidence_score(src, tgt)
            if score <= threshold:
                score = 0
            for t in tgt["claim_types"]:
                if t not in types:
                    types[t] = []
                types[t].append(score)
        return {t: np.mean(v) for t, v in types.items()}

    def evaluate_averitec_score(self, srcs, tgts):
        scores = []
        for src, tgt in zip(srcs, tgts):
            score = self.compute_pairwise_evidence_score(src, tgt)
            this_example_scores = [0.0 for _ in self.averitec_reporting_levels]
            for i, level in enumerate(self.averitec_reporting_levels):
                if score > level:
                    this_example_scores[i] = src["pred_label"] == tgt["label"]
            scores.append(this_example_scores)
        return np.mean(np.array(scores), axis=0)

    def evaluate_questions_only(self, srcs, tgts):
        import scipy.optimize
        all_utils = []
        for src, tgt in zip(srcs, tgts):
            src_questions = [qa["question"] for qa in src.get("evidence", [])[: self.max_questions]]
            tgt_questions = [qa["question"] for qa in tgt["questions"]]
            pairwise_scores = compute_all_pairwise_scores(src_questions, tgt_questions, self.pairwise_metric)
            assignment = scipy.optimize.linear_sum_assignment(pairwise_scores, maximize=True)
            utility = pairwise_scores[assignment[0], assignment[1]].sum() / float(len(tgt_questions))
            all_utils.append(utility)
        return np.mean(all_utils)

    def evaluate_questions_and_answers(self, srcs, tgts):
        import scipy.optimize
        all_utils = []
        for src, tgt in zip(srcs, tgts):
            src_strings = self.extract_full_comparison_strings(src, is_target=False)[: self.max_questions]
            tgt_strings = self.extract_full_comparison_strings(tgt)
            pairwise_scores = compute_all_pairwise_scores(src_strings, tgt_strings, self.pairwise_metric)
            assignment = scipy.optimize.linear_sum_assignment(pairwise_scores, maximize=True)
            utility = pairwise_scores[assignment[0], assignment[1]].sum() / float(len(tgt_strings))
            all_utils.append(utility)
        return np.mean(all_utils)

    def compute_pairwise_evidence_score(self, src, tgt):
        import scipy.optimize
        src_strings = self.extract_full_comparison_strings(src, is_target=False)[: self.max_questions]
        tgt_strings = self.extract_full_comparison_strings(tgt)
        pairwise_scores = compute_all_pairwise_scores(src_strings, tgt_strings, self.pairwise_metric)
        assignment = scipy.optimize.linear_sum_assignment(pairwise_scores, maximize=True)
        return pairwise_scores[assignment[0], assignment[1]].sum() / float(len(tgt_strings))

    def extract_full_comparison_strings(self, example, is_target=True):
        example_strings = []
        if is_target:
            for evidence in example.get("questions", []):
                answers = evidence["answers"] if isinstance(evidence["answers"], list) else [evidence["answers"]]
                for answer in answers:
                    s = evidence["question"] + " " + answer["answer"]
                    if answer.get("answer_type") == "Boolean":
                        s += ". " + answer["boolean_explanation"]
                    example_strings.append(s)
                if not answers:
                    example_strings.append(evidence["question"] + " No answer could be found.")
        else:
            for evidence in example.get("evidence", []):
                example_strings.append(evidence["question"] + " " + evidence["answer"])
        for s in example.get("string_evidence", []):
            example_strings.append(s)
        return example_strings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Baseline evaluation: veracity accuracy + F1 only."
    )
    parser.add_argument(
        "-i", "--prediction_file",
        default="results/predictions_for_eval.json",
    )
    parser.add_argument(
        "--label_file",
        default="../averitec/data/dev.json",
    )
    args = parser.parse_args()

    with open(args.prediction_file, encoding="utf-8") as f:
        predictions = json.load(f)
    with open(args.label_file, encoding="utf-8") as f:
        references = json.load(f)

    if len(predictions) != len(references):
        print(f"[WARN] {len(predictions)} predictions vs {len(references)} references — truncating references.")
        references = references[: len(predictions)]

    scorer = AVeriTeCEvaluator()

    # Only evaluate_veracity() is called — no evidence metrics.
    v_score = scorer.evaluate_veracity(predictions, references)

    print("=" * 60)
    print("Baseline Veracity Evaluation (LLM internal knowledge only)")
    print("=" * 60)
    print(f"\n  {'Accuracy':<43} {v_score['acc']:.4f}")
    print(f"\n  Per-class F1:")
    for label in scorer.verdicts:
        print(f"    {label:<41} {v_score[label]:.4f}")
    print(f"\n  {'Macro-F1':<43} {v_score['macro']:.4f}")
    print("=" * 60)
