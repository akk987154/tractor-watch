# ---------- 构建阶段 ----------
FROM python:3.12-slim AS builder

# 在独立虚拟环境里装依赖，方便整体拷贝到运行阶段
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# hatchling 是构建后端。显式安装并配合 --no-build-isolation，
# 避免 pip 在构建时隐式联网拉取构建依赖。
# 原 Dockerfile 的问题正在于此：它只把 --target=/deps 的内容拷进运行阶段，
# 而 hatchling 装在构建阶段自己的 site-packages 里，于是运行阶段的
# `pip install -e .` 必须联网重新下载 hatchling 才能完成构建。
RUN pip install --no-cache-dir --upgrade pip hatchling

WORKDIR /app

# 依赖清单先拷贝，利用 Docker 层缓存。
# requirements.txt 里是精确锁定的版本 —— pyproject.toml 用的是 `>=` 下限约束，
# 每次构建都会解析出不同的依赖图，无法复现，也无法审计。
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

COPY src/ src/
# --no-deps 很关键：否则 pip 会按 pyproject 的 `>=` 再解析一次依赖，
# 绕过上面刚刚锁定的版本
RUN pip install --no-cache-dir --no-build-isolation --no-deps .

# ---------- 运行阶段 ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

# 创建非 root 用户。原 Dockerfile 没有 USER 指令，容器与 SQLite 卷都以 root 运行，
# compose 挂载出来的 ./data 在宿主机上也会变成 root 属主。
RUN groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid app --home-dir /app app && \
    mkdir -p /app/data && \
    chown -R app:app /app

WORKDIR /app
USER 10001:10001

# 健康检查只对 api 服务有意义（tracker 不监听端口），
# 因此放在 docker-compose.yml 里按服务配置，而不是写死在这里。

CMD ["tractor-watch", "track"]
