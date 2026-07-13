#!/usr/bin/env python3
"""Write John Pratt's professional summary to a timestamped file on the Desktop.

Usage:
    python3 generate_summary.py        # write the built-in summary
    python3 generate_summary.py -      # read the summary text from stdin instead

Output: ~/Desktop/professional_summary_<YYYY-MM-DD_HHMMSS>.txt
Standard library only -- no dependencies, no network.
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_RAW_SUMMARY = """John Pratt -- Professional Summary

John Pratt is a cloud and platform engineer who designs, builds, and ships
autonomous, AI-driven systems end to end. He specializes in serverless
architecture on AWS (Lambda, EventBridge, SQS, DynamoDB), infrastructure-as-code
with Terraform, and backend development in Python and Node.js/TypeScript, with a
track record of turning ambiguous problems into production systems that run
themselves.

His work centers on automation and applied AI. Rainmaker is an agentic outbound
engine that fingerprints target companies, sends personalized outreach from real
inboxes, and uses an LLM to read and triage every reply on a 15-minute serverless
cadence. Wraith is an autonomous extraction pipeline spanning 71K+ lines of code
and 40+ TB transferred across 41 sites and multiple distributed machines. A fully
automated content pipeline reached 500K+ views hands-off. Across all of them he
owns the whole stack: data, infrastructure, orchestration, and the LLM/agent
layer that ties it together.

John holds 30+ professional certifications spanning the major clouds and
platforms, including AWS Certified Solutions Architect - Professional and DevOps
Engineer - Professional; Google Cloud Professional Cloud Developer, DevOps
Engineer, and Security Engineer; Microsoft Azure Solutions Architect Expert and
DevOps Engineer Expert; Certified Kubernetes Administrator (CKA); HashiCorp
Terraform; Databricks; Docker; Confluent Kafka; and SnowPro Core. The breadth
reflects how he works: fluent across cloud providers and able to reach for the
right tool rather than the familiar one.

Pragmatic and results-first, he is at his best shipping working software,
automating the tedious, and owning a system from architecture through deployment.

Portfolio: john-pratt.com   .   Contact: john@john-pratt.com
"""


def _unwrap(text: str) -> str:
    """Collapse the hard line breaks inside each paragraph to a single line,
    keeping the blank lines between paragraphs. The output .txt then has one
    line per paragraph and the editor soft-wraps it."""
    paragraphs = text.strip().split("\n\n")
    return "\n\n".join(" ".join(p.split()) for p in paragraphs)


SUMMARY = _unwrap(_RAW_SUMMARY)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "-":
        text = _unwrap(sys.stdin.read())  # normalize wrapped paragraphs from stdin too
    else:
        text = SUMMARY
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = Path.home() / "Desktop" / f"professional_summary_{stamp}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text.rstrip() + "\n", encoding="utf-8")
    print(out)

    # Open the summary in VS Code (uses the `code` CLI on PATH).
    try:
        subprocess.run(["code", str(out)], check=False)
    except FileNotFoundError:
        print(
            "VS Code 'code' command not found on PATH -- open the file manually.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
