# Limitations

- Chess Coach is for completed standard chess games. Chess.com imports depend
  on supported public archives and terminal result evidence. PGN completion
  relies on the submitted declaration and legal replay. The browser currently
  imports via Chess.com.
- Stockfish evaluations depend on the engine version, budget and position
  history. SetUp/FEN input has unknown earlier history. The application keeps
  mate separate from centipawns and uses automatic draw rules when evaluating
  stored positions.
- Historical summaries describe the selected games. The app suppresses
  some low-sample patterns. Changes after training are observational and
  reflect the available games, controls and analysis profile.
- Generated explanations can contain subtle chess errors or unsupported
  advice despite schema and factual checks. The app displays scores and move
  evidence separately. Model motif suggestions remain experimental pending
  independently reviewed holdout results.
- The default architecture assumes one local user, one SQLite library and
  loopback access. New imports depend on Chess.com, new analysis requires
  Stockfish and a compatible worker, and new explanations require the
  configured local model.
