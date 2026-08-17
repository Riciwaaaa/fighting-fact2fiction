#!/usr/bin/env python3
"""Run the frozen evidence mapper on the predeclared 0.75% and 1% extension."""

import run_evidence_signal


if __name__ == "__main__":
    run_evidence_signal.DEFAULT_CONDITIONS = (
        "fact2fiction_p0.0075",
        "fact2fiction_p0.01",
    )
    run_evidence_signal.main()
