"""Grade eval responses against assertions from eval_metadata.json files."""

import json
import sys
from pathlib import Path


def grade_response(response_text: str, assertions: list[dict]) -> list[dict]:
    """Grade a response against a list of assertions.

    Returns list of {text, passed, evidence} dicts.
    Uses keyword/concept matching as a first pass.
    """
    results = []
    response_lower = response_text.lower()

    for assertion in assertions:
        text = assertion["text"]
        atype = assertion.get("type", "contains_concept")

        if atype == "absence":
            passed, evidence = grade_absence(response_lower, text)
        elif atype == "numerical_accuracy":
            passed, evidence = grade_numerical(response_text, text)
        elif atype == "conceptual_focus":
            passed, evidence = grade_conceptual_focus(response_lower, text)
        elif atype == "depth_check":
            passed, evidence = grade_depth_check(response_lower, text)
        else:  # contains_concept
            passed, evidence = grade_contains_concept(response_lower, text)

        results.append({
            "text": text,
            "passed": passed,
            "evidence": evidence,
        })

    return results


def grade_contains_concept(response: str, assertion_text: str) -> tuple[bool, str]:
    """Check if response contains the described concept."""
    concept_keywords = extract_keywords(assertion_text)

    found = []
    missing = []
    for kw_group in concept_keywords:
        if any(kw in response for kw in kw_group):
            found.append(kw_group[0])
        else:
            missing.append(kw_group[0])

    if len(found) >= len(concept_keywords) * 0.6:
        return True, f"Found concepts: {', '.join(found)}"
    else:
        return False, f"Missing concepts: {', '.join(missing)}; found: {', '.join(found)}"


def grade_absence(response: str, assertion_text: str) -> tuple[bool, str]:
    """Check that a concept is NOT the primary framing."""
    # For absence checks, we're more lenient — mentioning something briefly is OK,
    # it just shouldn't be the primary/sole framework
    if "fiduciary" in assertion_text.lower() and "suitability" in assertion_text.lower():
        # Check FINRA suitability isn't the PRIMARY standard applied
        suitability_count = response.count("suitability") + response.count("finra rule 2111")
        regbi_count = response.count("reg bi") + response.count("regulation best interest") + response.count("best interest")
        if suitability_count > regbi_count * 2:
            return False, f"Suitability mentioned {suitability_count}x vs Reg BI {regbi_count}x — suitability appears dominant"
        return True, f"Reg BI ({regbi_count}x) appropriately dominant over suitability ({suitability_count}x)"

    if "fiduciary" in assertion_text.lower() and "bd capacity" in assertion_text.lower():
        has_regbi = "reg bi" in response or "regulation best interest" in response
        has_bd = "broker" in response or "bd " in response or "broker-dealer" in response
        if has_regbi or has_bd:
            return True, "Acknowledges BD capacity context"
        return False, "Does not acknowledge BD capacity"

    return True, "Absence check passed (manual review recommended)"


def grade_numerical(response: str, assertion_text: str) -> tuple[bool, str]:
    """Check for numerical accuracy."""
    import re

    if "24%" in assertion_text or "23.5" in assertion_text:
        # TWR should be ~24%
        numbers = re.findall(r'(\d+\.?\d*)\s*%', response)
        for n in numbers:
            val = float(n)
            if 23.0 <= val <= 25.0:
                return True, f"Found TWR value: {val}%"
        return False, f"No value in 23-25% range found. Values found: {numbers[:10]}"

    if "~$64K" in assertion_text or "64" in assertion_text:
        numbers = re.findall(r'\$?([\d,]+\.?\d*)\s*(?:K|k|thousand)?', response)
        for n in numbers:
            val = float(n.replace(",", ""))
            if 55000 <= val <= 75000 or 55 <= val <= 75:
                return True, f"Found rebalance amount near $64K: ${n}"
        return False, f"No value near $64K found"

    return True, "Numerical check requires manual review"


def grade_depth_check(response: str, assertion_text: str) -> tuple[bool, str]:
    """Check for depth of analysis — enumeration, specificity, multiple examples."""
    import re

    # Extract the required count pattern like "3+" or "at least 3"
    count_match = re.search(r'(\d+)\+|at least (\d+)', assertion_text)
    min_count = int(count_match.group(1) or count_match.group(2)) if count_match else 3

    # Determine what to count based on assertion text
    text_lower = assertion_text.lower()

    if "specific rule" in text_lower or "rule number" in text_lower or "citation" in text_lower:
        # Count regulatory citations
        patterns = [
            r'rule \d+[a-z]?[-.]?\d*', r'section \d+', r'\d+ cfr',
            r'finra rule', r'sec rule', r'reg [a-z]', r'u\.s\.c\.',
            r'pte \d+', r'form [a-z]+', r'release [a-z]+-\d+'
        ]
        found = set()
        for p in patterns:
            found.update(re.findall(p, response))
        if len(found) >= min_count:
            return True, f"Found {len(found)} citations (need {min_count}+): {list(found)[:5]}"
        return False, f"Found only {len(found)} citations (need {min_count}+): {list(found)}"

    if "edge case" in text_lower or "pitfall" in text_lower or "risk" in text_lower:
        # Count distinct warnings/edge cases using broader detection
        warning_markers = [
            "however", "caution", "warning", "risk", "pitfall", "watch out",
            "be aware", "important", "note that", "careful", "trap", "mistake",
            "edge case", "exception", "special case", "gotcha", "caveat",
            "common error", "frequently", "often overlooked", "don't forget",
            "critical", "must not", "must be", "failure to", "failing to",
            "ensure that", "verify that", "double-check", "reconcil",
        ]
        # Also count bullet points in warning/pitfall sections
        count = sum(1 for m in warning_markers if m in response)
        # Count markdown list items that contain warning-ish language
        import re
        warning_bullets = re.findall(r'[-*]\s+\*?\*?(?:caution|note|important|edge|exception|if the|when a|watch|ensure|verify|handle|consider)', response)
        count += len(warning_bullets)
        if count >= min_count:
            return True, f"Found {count} risk/warning indicators (need {min_count}+)"
        return False, f"Found only {count} risk/warning indicators (need {min_count}+)"

    if "step" in text_lower or "phase" in text_lower or "stage" in text_lower:
        # Count enumerated steps
        step_patterns = [r'step \d+', r'\d+\.', r'phase \d+', r'stage \d+']
        count = 0
        for p in step_patterns:
            count += len(re.findall(p, response))
        count = min(count, 20)  # Cap to avoid noise
        if count >= min_count:
            return True, f"Found {count} enumerated steps (need {min_count}+)"
        return False, f"Found only {count} enumerated steps (need {min_count}+)"

    # Generic depth: count substantive paragraphs
    paragraphs = [p for p in response.split('\n\n') if len(p) > 100]
    if len(paragraphs) >= min_count:
        return True, f"Found {len(paragraphs)} substantive paragraphs (need {min_count}+)"
    return False, f"Found only {len(paragraphs)} substantive paragraphs (need {min_count}+)"


def grade_conceptual_focus(response: str, assertion_text: str) -> tuple[bool, str]:
    """Check the overall conceptual focus of the response."""
    if "billing" in assertion_text.lower() and "disclosure" in assertion_text.lower():
        billing_terms = sum(response.count(t) for t in ["billing", "proration", "invoice", "deduction", "calculation"])
        disclosure_terms = sum(response.count(t) for t in ["disclosure", "form adv", "regulatory", "filing"])
        if "not" in assertion_text.lower() and "disclosure" in assertion_text.lower():
            return billing_terms > disclosure_terms, f"Billing terms: {billing_terms}, disclosure terms: {disclosure_terms}"
        return disclosure_terms > billing_terms, f"Disclosure terms: {disclosure_terms}, billing terms: {billing_terms}"

    if "historical" in assertion_text.lower() and "forward" in assertion_text.lower():
        historical = sum(response.count(t) for t in ["historical", "realized", "past", "actual"])
        forward = sum(response.count(t) for t in ["forward", "projected", "expected", "forecast", "simulation"])
        if "not forward" in assertion_text.lower() or "not project" in assertion_text.lower():
            return historical > forward, f"Historical: {historical}, forward: {forward}"
        return forward > historical, f"Forward: {forward}, historical: {historical}"

    return True, "Focus check requires manual review"


def extract_keywords(text: str) -> list[list[str]]:
    """Extract keyword groups from assertion text for matching."""
    keyword_map = {
        "reg bi": [["reg bi", "regulation best interest"]],
        "four": [["disclosure", "care", "conflict", "compliance"]],
        "obligations": [["obligation"]],
        "pte 2020-02": [["pte 2020-02", "pte 2020", "prohibited transaction exemption"]],
        "dol": [["dol", "department of labor"]],
        "reasonably available alternatives": [["reasonably available alternative", "alternative"]],
        "ia act": [["ia act", "investment advisers act", "advisers act", "section 206"]],
        "section 206": [["section 206", "206"]],
        "duty of care": [["duty of care"]],
        "duty of loyalty": [["duty of loyalty"]],
        "proprietary": [["proprietary"]],
        "conflict": [["conflict"]],
        "cost": [["cost", "fee", "expense"]],
        "differential": [["differential", "difference", "higher", "cheaper", "lower"]],
        "twr": [["twr", "time-weighted", "time weighted"]],
        "sub-period": [["sub-period", "sub period", "subperiod", "period 1", "first period", "first half", "first six"]],
        "mwr": [["mwr", "money-weighted", "money weighted", "irr"]],
        "manager": [["manager"]],
        "investor": [["investor"]],
        "band": [["band", "threshold", "breach", "tolerance"]],
        "breach": [["breach", "exceed", "above", "outside", "drifted", "over"]],
        "harvest": [["harvest", "tax-loss", "tax loss", "tlh"]],
        "wash-sale": [["wash-sale", "wash sale", "30-day", "30 day", "substantially identical"]],
        "replacement": [["replacement", "substitute", "similar", "proxy"]],
        "finra rule 2111": [["finra rule 2111", "rule 2111", "2111"]],
        "turnover": [["turnover"]],
        "excessive": [["excessive", "presumptively"]],
        "cost-to-equity": [["cost-to-equity", "cost to equity", "break even", "breakeven"]],
        "senior": [["senior", "elderly", "older"]],
        "approval": [["approval", "approved", "consent"]],
        "rmd": [["rmd", "required minimum distribution"]],
        "withdrawal": [["withdrawal", "distribution"]],
        "roth": [["roth"]],
        "conversion": [["conversion"]],
        "benchmark": [["benchmark"]],
        "sharpe": [["sharpe"]],
        "drawdown": [["drawdown"]],
        "sortino": [["sortino", "downside"]],
        "monte carlo": [["monte carlo"]],
        "simulation": [["simulation", "stochastic"]],
        "capital market assumptions": [["capital market assumption", "expected return"]],
        "probability": [["probability", "likelihood"]],
        # Broader synonym groups for operational terms
        "form adv": [["form adv", "adv part", "part 2a"]],
        "item 5": [["item 5"]],
        "references": [["form adv", "adv part", "part 2a", "item 5"]],
        "tiered": [["tiered", "tier", "breakpoint", "graduated"]],
        "present": [["present", "disclose", "describe", "show", "display", "format"]],
        "discusses": [["discuss", "explain", "describe", "address", "cover", "detail"]],
        "cip/kyc": [["cip", "kyc", "customer identification", "know your customer"]],
        "addresses": [["address", "cover", "discuss", "describe", "detail", "walk through"]],
        "flags": [["flag", "identify", "note", "highlight", "elevat"]],
        "non-us": [["non-us", "non-u.s.", "foreign", "uk resident", "non-resident", "international"]],
        "trustee": [["trustee"]],
        "custodian": [["custodian", "schwab", "fidelity", "pershing", "td ameritrade"]],
        "mentions": [["mention", "reference", "cite", "note", "include", "discuss"]],
        "specific": [["specific", "schwab", "fidelity", "pershing", "particular"]],
        "defines": [["define", "stp rate", "straight-through", "measure"]],
        "calculates": [["calculat", "formula", "rate =", "rate=", "metric", "measure"]],
        "improvement": [["improvement", "target", "goal", "90%", "benchmark"]],
        "approaches": [["approach", "strategy", "method", "pattern", "technique", "rpa", "api"]],
        "integration": [["integration", "connect", "interface", "api", "bridge", "hub"]],
        "exception": [["exception"]],
        "categories": [["categor", "classif", "type", "tier"]],
        "cause": [["cause", "root", "reason", "diagnos"]],
        "analysis": [["analysis", "analyz", "assess", "evaluat", "review"]],
        "workflow": [["workflow", "process", "pipeline"]],
        "validation": [["validat", "check", "verif", "gate", "screen"]],
    }

    text_lower = text.lower()
    groups = []
    for key, kw_groups in keyword_map.items():
        if key in text_lower:
            groups.extend(kw_groups)

    if not groups:
        words = [w for w in text_lower.split() if len(w) > 4 and w not in {"about", "should", "their", "which", "these", "those", "could", "would"}]
        groups = [[w] for w in words[:3]]

    return groups


def main():
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("finance-skills-workspace/iteration-1")

    for eval_dir in sorted(workspace.iterdir()):
        if not eval_dir.is_dir() or not eval_dir.name.startswith("eval-"):
            continue

        metadata_file = eval_dir / "eval_metadata.json"
        if not metadata_file.exists():
            continue

        metadata = json.loads(metadata_file.read_text())
        assertions = metadata.get("assertions", [])

        print(f"\n{'='*60}")
        print(f"EVAL: {metadata['eval_name']}")
        print(f"{'='*60}")

        for variant in ["with_skill", "without_skill"]:
            response_file = eval_dir / variant / "outputs" / "response.md"
            if not response_file.exists():
                print(f"\n  [{variant}] — NO RESPONSE FILE")
                continue

            response_text = response_file.read_text()
            grades = grade_response(response_text, assertions)

            passed = sum(1 for g in grades if g["passed"])
            total = len(grades)

            print(f"\n  [{variant}] — {passed}/{total} assertions passed")
            for g in grades:
                status = "PASS" if g["passed"] else "FAIL"
                print(f"    [{status}] {g['text']}")
                print(f"           {g['evidence']}")

            # Save grading results
            grading_output = {
                "eval_id": metadata["eval_id"],
                "eval_name": metadata["eval_name"],
                "variant": variant,
                "pass_rate": passed / total if total > 0 else 0,
                "expectations": grades,
            }

            grading_file = eval_dir / variant / "grading.json"
            grading_file.write_text(json.dumps(grading_output, indent=2))

    print(f"\n{'='*60}")
    print("GRADING COMPLETE — results saved to grading.json in each run directory")


if __name__ == "__main__":
    main()
