# Dead end — kept for the record

Claims 7, 32, 34, 36, 63, 75 were meant to extend the Supported half of a balanced set.
They have Fact2Fiction poison artifacts, but under **other** fact-checker/attacker model
pairs (gemini_35_flash, minimax_m3, deepseek_v4_flash), not the `fc-mimo_v25_pro_att-
deepseek_v4_flash` pair this project uses. Pass C therefore failed for all six with
"no cached poison artifacts".

`answers_clean.json` and `answers_model_only.json` here are complete and would be reusable
if those artifacts are ever generated for the mimo pair. Nothing else in this directory is.

Superseded by 10/, 11/ and 12/ — see ../README.md.
