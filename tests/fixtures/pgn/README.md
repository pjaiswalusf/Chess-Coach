# Phase 8 fixtures (v1)

All games are hand-written synthetic inputs, with no private source data.

| File | Expected |
| --- | --- |
| white_win | 6 plies, White win without terminal board; no clocks/opening |
| black_win | 4 plies, Black checkmate |
| draw | 2 plies, agreed draw without terminal board |
| checkmate | 7 plies, White checkmate |
| timeout | 2 plies, supplied timeout reason; not checkmate |
| clocks | 4 mainline plies, variation excluded; White clock 275/272, recorded elapsed 8 then estimated 8; Black estimated 15 then unknown |
| custom | 2 plies starting Black move 20, unknown prior history and first elapsed time |
| illegal | INVALID_MOVES |
| invalid_fen | INVALID_START_POSITION |
| missing_player | INVALID_PLAYER_METADATA |

Unit tests derive malformed, missing-result, unsupported-variant and multi-game
cases from these fixed strings, with explicit expected rejection codes.
