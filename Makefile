.PHONY: build-ui dev build release

build-ui:
	cd frontend && npm ci && npm run build

dev:
	@echo "Start 'qara serve' in one terminal, then run 'cd frontend && npm run dev' in another."

build: build-ui
	hatch build

release: build
	hatch publish
