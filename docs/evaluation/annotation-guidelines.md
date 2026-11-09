# Annotation guidelines — motif-v1

Assign one primary theme to a completed-game move. First replay the legal
played move and the relevant engine lines. Record the source game and ply,
supporting facts, reviewer, and any alternative label considered. Engine
scores are estimates at the recorded budget. They do not prove player intent.
Review independently of model predictions. Adjudicate disagreements before
freezing labels, and keep all positions from a game in a single split.

| Label | Required evidence and positive example | Boundary, negative example, or reason to abstain |
| --- | --- | --- |
| `HANGING_PIECE` | The played move allows avoidable net material loss involving a non-pawn piece. For example, a quiet rook move leaves a knight capturable without recapture or compensation in the supplied lines. | A queen exchange is not a hanging piece. Abstain when compensation or continuation is unclear. |
| `MISSED_TACTIC` | The alternative contains a concrete forcing opportunity lost after the played move, such as a verified missed mate or winning fork. | Another continuation retaining the tactic is not a miss. A score gap alone is not tactical evidence. |
| `KING_SAFETY` | The move creates or fails to address a concrete king threat, such as allowing a new forced back-rank mate. | An already unavoidable mate is not newly allowed. Prefer `MISSED_TACTIC` if the primary evidence is the mover's lost attacking opportunity. |
| `DEVELOPMENT` | A demonstrable development problem drives the mistake, such as neglecting a development move and allowing a concrete threat that the developed piece would stop. | Moving the same piece twice can be correct. Abstain without a demonstrated consequence. |
| `BAD_TRADE` | A voluntary exchange has a verified unfavorable consequence, such as trading into a demonstrably lost pawn ending. | An ordinary equal trade or an undefended piece dropped without an exchange does not qualify. |
| `PAWN_STRUCTURE` | A verified structural weakness drives the consequence, such as creating a backward pawn that the shown sequence wins. | Doubled pawns alone do not establish a mistake. Prefer a more direct tactical label if the structure is incidental. |
| `ENDGAME_TECHNIQUE` | The position is an endgame and a demonstrable technique is central, such as relinquishing opposition and allowing a promotion in the verified line. | A plain piece drop in an endgame may still be `HANGING_PIECE`. Abstain if the technical claim depends on an unverified line. |
| `CONVERSION` | The mover loses a sustained engine-estimated advantage; the recorded continuation and estimates support the transition. | A small fluctuation is not conversion failure. Prefer a specific tactical or technical theme when that is better supported. |
| `OTHER` | A well-supported mistake fits none of the substantive classes, such as a verified loss of an immediate draw opportunity outside those classes. | Use abstention for incomplete evidence or unresolved competing labels; `OTHER` is not an uncertainty bucket. |

Confirmed events carry detector versions and evidence references. Model
suggestions are provisional; human-reviewed labels are separate evaluation
records. Abstain on missing or ambiguous evidence. Do not infer calculation,
opening knowledge, defensive awareness, or time management from an engine line.
Some taxonomy labels require richer evidence than the initial automatic
detectors supply. Their absence from model output must be reported as a
coverage limitation, rather than weakening the rules for valid references.
