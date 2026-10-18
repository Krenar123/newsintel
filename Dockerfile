FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy models
RUN python -m spacy download en_core_web_sm && \
    python -m spacy download xx_ent_wiki_sm

# Download NLTK data for sumy and sentiment
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('vader_lexicon')"

# Copy application
COPY . .

# Create directories
RUN mkdir -p reports ml_models

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
