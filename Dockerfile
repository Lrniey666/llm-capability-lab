# llm-capability-lab HTTP 服務
#
# 只裝函式庫與服務層。menu_example/ 與 docs/ 是研究資產，不進映像檔——
# 要在容器裡跑研究模組的話，把 repo 掛進去並設 LLMCLAB_WORKSPACE。

FROM python:3.12-slim AS build

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY llmclab ./llmclab
RUN pip install --no-cache-dir --upgrade pip build \
    && python -m build --wheel --outdir /dist


FROM python:3.12-slim

# 不用 root 跑服務
RUN useradd --create-home --uid 10001 llmclab

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=build /dist/*.whl /tmp/
# 裝「這一顆」wheel 的 [serve]，不要再向 PyPI 解析同名專案。
RUN WHL=$(echo /tmp/*.whl) \
    && pip install --no-cache-dir "${WHL}[serve]" \
    && rm -f ${WHL}

USER llmclab
WORKDIR /home/llmclab

EXPOSE 8000

# 容器裡要對外，所以綁 0.0.0.0；對外暴露請放在反向代理後面。
# LLMCLAB_API_TOKEN 未設定時服務會拒絕啟動，這是刻意的。
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status==200 else 1)"

CMD ["llmclab", "serve", "--host", "0.0.0.0", "--port", "8000"]
