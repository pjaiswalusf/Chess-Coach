# Demonstration

This capture uses a fresh synthetic Chess.com archive and an isolated migrated
SQLite database. SvelteKit, FastAPI, job processing, persistence and training
run through the application. The source, engine scores and model prose are
fixture outputs. The System screen reports fixture adapter capabilities.

## Captures

- [Browser walkthrough](workflow.webm), a roughly 50-second silent fixture recording.
- [Dashboard](dashboard.png) with the synthetic library, phase counts and sample limits.
- [Game review](game-review.png) with the played move, simulated engine score and fixture explanation.
- [Coaching](coaching.png) with the pattern's frequency, sample size and source links.
- [Training](training.png) with a verified fixture solution and scheduled review.
- [System](system.png) with adapter status and simulated performance counters.
  See [M5 benchmarks](../BENCHMARKS.md) for actual performance measurements.

## Record again

Install the locked dependencies and Chromium as described in [Testing](../TESTING.md).
From `frontend/`, choose a new output directory and run the existing complete
workflow test with capture enabled.

```sh
demo_dir="$(mktemp -d)"
CHESS_COACH_DEMO_DIR="$demo_dir" pnpm test:e2e e2e/complete-workflow.spec.ts
```

The output directory receives the five screenshots and a single silent browser
recording. The database is fresh and the test deletes it after capture.

## Walkthrough

1. Show the empty Dashboard and the recovery message for a source outage.
2. Import the fixture archive, then repeat sync to show the zero-new-games result.
3. Queue analysis. Open the stored critical move, its evaluation and explanation.
4. Open Coach and trace a repeated opening error to measured evidence.
5. Solve the personalized puzzle and view the scheduled review.
6. Open System, then show that the saved report and attempt survive API restart
   with the fixture model unavailable.
