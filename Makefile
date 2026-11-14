# Aftershock. `make replay` needs only Python 3.9+ : no keys, no network, nothing to install.
PY ?= python3

.PHONY: replay verify test live settle serve contract deploy record view

replay:            ## rebuild results.json, THESIS.md and the page data from the committed snapshot and recorded model replies
	AFTERSHOCK_MODE=replay $(PY) -m aftershock.run

verify: replay     ## replay, then show that nothing changed (the rebuild is identical to what is committed)
	git diff --exit-code --stat -- results.json THESIS.md docs/data.js && echo "IDENTICAL: the replay rebuilt the committed results byte for byte."

test:              ## unit tests: event finder, event test (synthetic series with a known jump), decision rule, reply validation
	$(PY) -m unittest discover -s tests -v

live:              ## refetch the three sources, re-run every model (needs NVIDIA_API_KEY and network)
	$(PY) -m aftershock.fetch sources
	$(PY) -m aftershock.fetch headlines
	AFTERSHOCK_MODE=live $(PY) -m aftershock.run

settle:            ## recompute due forecasts and record the outcomes on the testnet contract (needs the testnet key)
	$(PY) -m aftershock.settle
	cd chain && npm install --no-audit --no-fund --silent && node chain.mjs settle
	AFTERSHOCK_MODE=replay $(PY) -m aftershock.run

serve:             ## open the page at http://localhost:8000
	$(PY) -m http.server 8000 --directory docs

contract:          ## build the Rust contract and run its unit tests
	cd contract && cargo test && cargo build --target wasm32-unknown-unknown --release

deploy: contract   ## testnet only: create a faucet account (once) and deploy
	cd chain && npm install --no-audit --no-fund --silent && (test -f $$HOME/.aftershock/testnet-key.json || node chain.mjs create) && node chain.mjs deploy

record:            ## testnet only: record the run and post its forecasts
	cd chain && node chain.mjs record
	AFTERSHOCK_MODE=replay $(PY) -m aftershock.run

view:              ## print what the contract holds (no key needed)
	cd chain && npm install --no-audit --no-fund --silent && node chain.mjs view
