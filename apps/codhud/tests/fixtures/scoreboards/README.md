Real end-of-game scoreboards, each a picture (`.png`) and what it says
(`.json`, `{"read": {"teams": [...]}}`). tests/test_cod.py reads every one.

The HUD keeps each scoreboard it sees in `data\codhud\scoreboards` (the
picture and what it read, or `-error` and why not). To add one here, copy
both files, and fix the numbers in the `.json` if they were misread.
