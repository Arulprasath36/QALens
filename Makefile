.PHONY: build-ui dev build check-package release release-test

build-ui:
	cd frontend && npm ci && npm run build

dev:
	@echo "Start 'qalens serve' in one terminal, then run 'cd frontend && npm run dev' in another."

build: build-ui
	hatch build

check-package: build
	python -m pip install --upgrade twine
	twine check dist/*

release-test: check-package
	hatch publish -r test

release: check-package
	hatch publish
