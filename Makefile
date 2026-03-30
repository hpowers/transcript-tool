install-tool:
	uv tool install --force git+ssh://git@github.com/hpowers/transcript-tool.git

upgrade-tool:
	uv tool upgrade transcribe

release-patch:
	python scripts/bump_version.py patch

release-minor:
	python scripts/bump_version.py minor

release-major:
	python scripts/bump_version.py major
