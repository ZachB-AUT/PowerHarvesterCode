# AI Usage Declaration

Large Language Models were used to help automate writing specific sections of this simulator.

All AI tasks were delegated to instances of Claude Opus 5.5.

AI was used for the following purposes:

- Debugging.
  - LLMs were used to debug code and fix some issues with FEMM and WINE.
- Parallelisation
  - Solving one design can take several minutes. When evaluating hundreds of thousands of designs, this leads to extremely long simulation times (potentially on the order of days for large numbers of large cores). Because of this, I used an LLM to assist with parallelising the existing code.
  - This affects the files:
    - `run_parallel.sh`
    - `sweep_worker.py`
- Figure generation:
  - I used an LLM to generate the programs to produce some figures. I checked these myself and take responsibility for their content.
  - This affects the files:
    - `plot_sweep.py`
    - `plot_winner.py`
- Procedural work:
  - During the early phases of writing this, I ran the programs manually. I used AI to generate the `Makefile`, which automates some of the work of running things.
  - This affects the files:
    - `makefile`
- Making it so the program can resume.
  - Following a computer crash that lead to the loss of 6 hours of simulation time, I had an LLM modify `harvester-reimplementation` to save results as it goes.

Files created by AI but contain content I wrote:

- `simulate_design.py`: This was factored out of `harvester-reimplementation.py` by an LLM but is essentially logic I wrote.
