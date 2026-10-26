Import:

- repeated sync produces zero duplicates
- incremental sync imports only unseen games

Chess correctness:

- 100% stored moves replay legally
- 100% best moves returned by Stockfish are legal
- evaluation orientation tests pass for White and Black

Caching:

- rerunning analysis on an unchanged DB causes zero
  unnecessary Stockfish analyses

LLM:

- structured response parsing >= 99%
- factual contradiction rate < 2%
- no LLM-generated numeric statistics

Analytics:

- every coaching claim has supporting sample size
- low-sample patterns are suppressed

Reliability:

- interrupted analysis can resume
- one failed game does not corrupt the whole batch

Quality:

- motif classification >= 80% on coarse human-labeled taxonomy

Testing:

- core pipeline coverage >= 90%
- overall test coverage >= 80%
