# Power-line energy harvester simulation. See README.md.
#
#   make sweep        coarse parameter sweep (one FEMM, hours)
#   make fine         finer sweep around the coarse winner
#   make light        sweep of light (<= 600 g) designs
#   make parallel PHASE=coarse|fine|light [JOBS=8]
#                     any of those three on JOBS FEMM copies at once
#   make plots        figures/ from the sweep results (no FEMM needed)
#   make validate     check the model against published experiments
#   make currents     line-current statistics from the Kikiwa data
#   make reset        kill a stuck FEMM/Wine and clear pyFEMM's link files
#
# FEMM runs under Wine and needs an X display even when minimised; without one
# it exits at startup and pyFEMM waits for it forever. So headless runs borrow
# a display for FEMM: a virtual one from xvfb-run if it is installed,
# otherwise the desktop session's display HEADLESS_DISPLAY, where FEMM's
# minimised window briefly appears. A timeout turns any remaining hang into an
# error.

FEMM_BIN := $(HOME)/.wine/drive_c/femm42/bin
HEADLESS_DISPLAY ?= :0
TIMEOUT ?= 100000
JOBS ?= 8

PYTHON := uv run python
SCRIPT ?= harvester-reimplementation.py
export WINEDEBUG := -all

ifdef DISPLAY
RUN := $(PYTHON) $(SCRIPT)
else
export MPLBACKEND := Agg
XVFB_RUN := $(shell command -v xvfb-run 2>/dev/null)
ifneq ($(XVFB_RUN),)
RUN := timeout $(TIMEOUT) $(XVFB_RUN) -a $(PYTHON) $(SCRIPT)
else
X_SOCKET := /tmp/.X11-unix/X$(subst :,,$(HEADLESS_DISPLAY))
RUN := DISPLAY=$(HEADLESS_DISPLAY) timeout $(TIMEOUT) $(PYTHON) $(SCRIPT)
endif
endif

.PHONY: run sweep fine light parallel plots validate currents reset
.DEFAULT_GOAL := sweep

# Run SCRIPT with a display for FEMM
run:
ifdef X_SOCKET
	@test -S $(X_SOCKET) || { \
		echo "No X display at $(HEADLESS_DISPLAY) for FEMM. Log in to the desktop," \
		     "install xvfb (xorg-server-xvfb / xvfb), or set HEADLESS_DISPLAY=:N."; exit 1; }
endif
	@$(RUN) || { status=$$?; \
		[ $$status -eq 124 ] && echo "Timed out after $(TIMEOUT) s; FEMM may be stuck, try 'make reset'."; \
		exit $$status; }

sweep:
	@$(MAKE) --no-print-directory run SCRIPT=harvester-reimplementation.py

fine:
	@$(MAKE) --no-print-directory run SCRIPT=fine_sweep.py

light:
	@$(MAKE) --no-print-directory run SCRIPT=light_sweep.py

parallel:
	@test -n "$(PHASE)" || { echo "usage: make parallel PHASE=coarse|fine|light [JOBS=8]"; exit 1; }
	DISPLAY=$${DISPLAY:-$(HEADLESS_DISPLAY)} ./run_parallel.sh $(PHASE) $(JOBS)

plots:
	MPLBACKEND=Agg $(PYTHON) plot_sweep.py
	MPLBACKEND=Agg $(PYTHON) plot_winner.py

validate:
	MPLBACKEND=Agg $(PYTHON) validation/validate_circuit.py
	MPLBACKEND=Agg $(PYTHON) validation/validate_femm.py
	$(PYTHON) validation/gapped_ring_check.py

# currents:
# 	$(PYTHON) line_current_stats.py

reset:
	-pkill -f 'python[0-9.]* (harvester-reimplementation|fine_sweep|light_sweep|sweep_worker)\.py'
	-wineserver -k
	rm -f $(FEMM_BIN)/ifile.txt $(FEMM_BIN)/ofile.txt
