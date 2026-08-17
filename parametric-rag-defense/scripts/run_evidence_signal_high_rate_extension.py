#!/usr/bin/env python3
"""Run the frozen evidence mapper on the predeclared 4% and 8% extension."""

import run_evidence_signal


if __name__ == "__main__":
    run_evidence_signal.DEFAULT_CONDITIONS = (
        "fact2fiction_p0.04",
        "fact2fiction_p0.08",
    )
    run_evidence_signal.main()
