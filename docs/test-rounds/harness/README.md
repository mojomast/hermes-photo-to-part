# Round harness

Copied from the test box with machine paths replaced by env vars. Set `HERMES_HOME` (test home) and `ROUND_DIR` (round folder, one subfolder per case with `prompt.txt` and the photo).

- `run.sh <case>`: one real-photo case (`timeout 2400 hermes chat --query-file prompt.txt --image <img> --oneshot --yolo --max-turns 40`).
- `he_run.sh <task>`: one sealed eval staged in `$ROUND_DIR/he/<task>` (via `python -m evals.runner --stage DIR --task ID`).
- `sealed_eval_ids.txt`: the 18 sealed task ids.
- `case-prompts/`: r15 prompts for the 8 real-photo cases (photos are not committed; they lived beside each prompt on the test box).
- `dump.py`: dumps tool calls for a session from `$HERMES_HOME/state.db`. Only run it after all runs finish (reading the DB while runs are live can kill leases).
- `gate_sanity_build.py`: r15 build-approval gate sanity script.

Launch detached: `setsid nohup bash run.sh a_gear >/dev/null 2>&1 &`. Keep this harness outside any directory the agent can reach.
