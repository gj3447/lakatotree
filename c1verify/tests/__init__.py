# c1verify.tests — shipped as a subpackage so the clean-venv CI job can run
# `pytest --pyargs c1verify.tests` against the INSTALLED package (repo not on sys.path),
# which is what makes engine-absence a construction fact rather than a promise.
