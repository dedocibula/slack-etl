.PHONY: run-now status logs pause resume gen-plist

PYTHON := uv run python
PLIST  := $(HOME)/Library/LaunchAgents/com.slack-etl.daily.plist
LABEL  := com.slack-etl.daily

# Run the full pipeline immediately
run-now:
	$(PYTHON) main.py

# Show launchd job status and last few log lines
status:
	@launchctl list | grep $(LABEL) || echo "Job not loaded"
	@echo "--- Last 20 log lines ---"
	@tail -20 logs/etl.log 2>/dev/null || echo "(no log yet)"

# Tail the rotating log file live
logs:
	@tail -f logs/etl.log

# Unload the launchd job (pause scheduling)
pause:
	launchctl unload $(PLIST) && echo "Paused"

# Load the launchd job (resume scheduling)
resume:
	launchctl load $(PLIST) && echo "Resumed"

# Generate the .plist file and print install instructions
gen-plist:
	$(PYTHON) launchd_gen.py

# Remove generated output (keeps DB and attachments)
clean:
	rm -rf logs/*.log data/**/*.md
