# Hugging Face Space image for the reel maker.
#
# Docker rather than the Gradio SDK because the pipeline shells out to ffmpeg
# and yt-dlp, and needs a TrueType font on disk for the captions -- none of
# which the plain Python image carries.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        git \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as uid 1000, so everything the app writes -- the
# model cache, work/, output/ -- has to belong to that user or the first run
# dies on a permission error.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    TORCH_HOME=/home/user/.cache/torch \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir yt-dlp

COPY --chown=user reels.py serve.py app.py ./
RUN mkdir -p work output

EXPOSE 7860
CMD ["python", "app.py"]
