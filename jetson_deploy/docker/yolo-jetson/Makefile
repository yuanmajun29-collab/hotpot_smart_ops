.PHONY: install test build-docker deploy-jetson deploy dev-jetson infer-jetson sync clean

install:
	pip install -e .

test:
	python3 -m pytest tests/ -v

# ── 本地构建 ──────────────────────────────────────────

build-docker:
	docker build -t yolo-jetson-infer:local -f docker/yolo-jetson/Dockerfile .

# ── 部署到 Jetson ─────────────────────────────────────

# 推送镜像到 Jetson（save + scp + load）
deploy-jetson:
	@echo "==> Saving image to /tmp/yolo-jetson-infer.tar ..."
	docker save yolo-jetson-infer:local -o /tmp/yolo-jetson-infer.tar
	@echo "==> Copying to Jetson (192.168.2.240) ..."
	scp /tmp/yolo-jetson-infer.tar root@192.168.2.240:/tmp/
	@echo "==> Loading on Jetson ..."
	ssh root@192.168.2.240 "docker load -i /tmp/yolo-jetson-infer.tar && rm /tmp/yolo-jetson-infer.tar"
	@echo "==> Cleaning local tarball ..."
	rm /tmp/yolo-jetson-infer.tar
	@echo "==> Deploy complete: yolo-jetson-infer:local pushed to Jetson."

# 一键部署：构建 + 推送
deploy: build-docker deploy-jetson

# ── Jetson 上运行 ────────────────────────────────────

# 在 Jetson 上进入交互式 shell（SSH + Docker）
dev-jetson:
	ssh -t root@192.168.2.240 "cd /root/yolo-jetson && ./run.sh"

# 在 Jetson 上执行一行命令
infer-jetson:
	ssh root@192.168.2.240 "cd /root/yolo-jetson && ./run.sh $(CMD)"

# ── 开发辅助 ──────────────────────────────────────────

sync:
	bash scripts/baidu-sync-dev-myjetson.sh

clean:
	rm -rf results/ runs/ __pycache__/ .venv/ .venv-tmp/ *.egg-info/
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete
