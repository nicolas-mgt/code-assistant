.PHONY: check build push bootstrap deploy login client smoke status models configure zed-config key-copy login-stop

check:
	caddy validate --config client/Caddyfile --adapter caddyfile
	python3 -m unittest discover -s tests -v

build push bootstrap deploy login client smoke status models configure zed-config key-copy login-stop:
	@python3 scripts/manage.py $@
